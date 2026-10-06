"""Giao bài / thu bài / nhật ký (Sổ tay 7.3) — thay `/upload_work`, `/send_work`, `/hub_send_work`, `/send_status`,
`/hub_pushed_list`, `/hub_delete_pushed`, `/collect_work`, `/hub_collect_work`, `/collect_status`,
`/hub_collect_status`, `/collect_download(_all)` của hub cũ. Agent v2 KHÔNG đổi gì: vẫn nhận `receive_work` /
`collect_work`, tải `/work_file`, nộp `/collect_upload`, báo `/send_report` + `/collect_report`
(legacy_adapter/http_routes.py gọi 2 móc ở cuối tệp).

Khác hub cũ (đều vì an toàn dữ liệu máy trạm — luật §0):
- `pushed_files` CHỈ ghi tệp agent BÁO đã ghi thật. Hub cũ ghi sổ mọi tệp × mọi máy lúc gửi, kể cả tệp agent "đã có, bỏ
  qua" (không ghi đè) → "Xoá tệp đã giao" xoá luôn tệp SẴN CÓ của máy (agent xoá bằng rmtree nếu là thư mục).
- Từ chối đích giao bài trong `Windows` và thư mục cài agent (ghi đè Client_Manager.exe = mất máy); từ chối "xoá nguồn
  sau khi thu" ở gốc ổ đĩa / thư mục hệ thống; mẫu tệp không được chứa đường dẫn (agent glob `src/**/<mẫu>` — mẫu
  `../../x` lọt ra ngoài thư mục nguồn rồi còn bị XOÁ).
- Phiên (send/collect) lưu MongoDB `command_results` (2 ngày), tạo TRƯỚC khi gửi lệnh; "máy đã nhận giao bài gần nhất"
  (để thu bài biết máy nào thiếu) đọc từ phiên giao ≤ 12 giờ — không giữ RAM (luật §0.3).
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import IO, Any

from pymongo.database import Database

from app.control.targets import LoiDich
from app.control.targets import resolve as resolve_devices
from app.devices import service as devices
from app.legacy_adapter.identity import is_teacher_pc, norm_host
from app.legacy_adapter.store import Store, hexid
from app.storage import KhoaSai, TenantFiles, safe_parts, safe_segment
from app.storage.base import CHUNK
from app.tenants.context import Ctx
from app.tenants.repo import repo_for
from app.work.paths import dest_dir, full_path, norm_ca, on_dinh

log = logging.getLogger("work")
SEND_BASE_S, SEND_PER_FILE_S, SEND_MAX_S = 120, 60, 3600
COLLECT_DEADLINE_S = 240  # agent: nén + nộp (timeout 180 s) + báo cáo
SENT_WINDOW = timedelta(hours=12)
MODES = ("students", "teachers", "all")
_MAU = re.compile(r"^[^\\/:]{1,64}$")


# ====================================================================== chốt an toàn đường dẫn máy trạm
def _norm_win(p: str) -> str:
    return re.sub(r"[\\/]+", "\\\\", str(p or "").strip()).rstrip("\\").lower()


def _duoi(p: str, *goc: str) -> bool:
    """p nằm trong (hoặc là) một trong các thư mục `goc` (không phân biệt ổ đĩa)."""
    s = _norm_win(p)
    s = s[2:] if re.match(r"^[a-z]:", s) else s
    return any(s == g or s.startswith(g + "\\") for g in goc)


def dest_bi_cam(dest: str) -> str:
    if not dest.strip():
        return ""
    if not re.match(r"^[A-Za-z]:[\\/]", dest.strip()):
        return "Thư mục đích phải là đường dẫn tuyệt đối (vd. C:\\BaiTap) hoặc để trống = Desktop chung"
    if _duoi(dest, "\\windows", "\\program files\\phenikaait", "\\program files (x86)\\phenikaait",
             "\\programdata\\phenikaait"):
        return "Không giao bài vào thư mục Windows hoặc thư mục của agent (ghi đè có thể làm hỏng máy / mất kết nối)"
    return ""


def nguon_bi_cam(src: str, delete_after: bool) -> str:
    if not re.match(r"^[A-Za-z]:[\\/]", src.strip()):
        return "Thư mục nguồn phải là đường dẫn tuyệt đối (vd. C:\\Users\\Public\\Desktop\\BaiTap)"
    if delete_after:
        s = _norm_win(src)
        if re.fullmatch(r"[a-z]:", s) or _duoi(src, "\\windows", "\\program files", "\\program files (x86)",
                                                "\\programdata"):
            return "Không xoá nguồn ở gốc ổ đĩa hoặc thư mục hệ thống — chọn đúng thư mục bài làm"
    return ""


def mau_hop_le(patterns: list[str]) -> list[str]:
    out = [p.strip() for p in patterns if p and p.strip()]
    for p in out:
        if not _MAU.match(p) or ".." in p:
            raise LoiDich(f"Mẫu tệp không hợp lệ: {p!r} (chỉ tên/đuôi như *.docx, không chứa \\ / : ..)")
    return out or ["*"]


# ====================================================================== máy đích
def targets(db: Database, ctx: Ctx, ad: Any, *, room_ids: list[str], device_ids: list[str],
            mode: str) -> tuple[list[dict], list[dict]]:
    """Máy đích theo NHIỀU phòng (mode: students = máy SV · teachers = máy GV · all) HOẶC danh sách máy (bỏ qua mode).
    Luôn lọc phạm vi phòng + tổ chức (như control.targets)."""
    if bool(room_ids) == bool(device_ids):
        raise LoiDich("Cần đúng một trong hai: các phòng hoặc danh sách máy")
    if device_ids:
        found, skipped = resolve_devices(db, ctx, ad, device_ids=device_ids)
        return [{**d, "room_name": d.get("room_name") or ""} for d in found], skipped
    out: list[dict] = []
    skipped: list[dict] = []
    for rid in dict.fromkeys(room_ids):
        room = devices.get_room(db, ctx, ad, rid)
        if room is None:
            skipped.append({"id": rid, "reason": "không có phòng này hoặc ngoài phạm vi được giao"})
            continue
        for d in room["devices"]:
            gv = is_teacher_pc(d.get("hostname"))
            if mode == "students" and gv:
                skipped.append({"hostname": d["hostname"], "reason": "máy giảng viên"})
                continue
            if mode == "teachers" and not gv:
                continue
            out.append({**d, "room_id": room["id"], "room_name": room["name"]})
    return out, skipped


def _info(d: dict) -> dict:
    return {"hostname": norm_host(d["hostname"]), "device_id": d.get("id"), "room_id": d.get("room_id"),
            "room_name": d.get("room_name") or ""}


def _dispatch(ad: Any, tg: list[dict], cmd: dict) -> tuple[list[dict], list[dict]]:
    sent, skipped = [], []
    for d in tg:
        if not d.get("is_online"):
            skipped.append({"hostname": d["hostname"], "reason": "máy đang tắt"})
            continue
        r = ad.dispatch(norm_host(d["hostname"]), d.get("mac") or "", {"command_obj": cmd})
        if r["channel"] == "none":
            skipped.append({"hostname": d["hostname"], "reason": "mất kênh lệnh"})
        else:
            sent.append({"hostname": norm_host(d["hostname"]), "channel": r["channel"]})
    return sent, skipped


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _elapsed(meta: dict, now: datetime | None) -> float:
    return ((now or datetime.now(UTC)) - datetime.fromisoformat(meta["started_at"])).total_seconds()


# ====================================================================== lô tệp giao
def upload(kho: TenantFiles, *, uid: str, may_all: bool, batch: str | None, name: object, stream: IO[bytes]) -> dict:
    """Thêm MỘT tệp vào lô (lô mới nếu `batch` rỗng). Tên giữ đường dẫn con (chọn cả thư mục) theo luật của agent."""
    bid = hexid(batch) if batch else uuid.uuid4().hex
    if batch:
        if len(bid) < 8:
            raise LoiDich("Mã lô không hợp lệ")
        owners = {d.get("by") for d in kho.list("work", bid)}
        if owners and not may_all and owners != {uid}:
            raise PermissionError("Lô tệp của người khác")
    rel = on_dinh(name)
    doc = kho.save("work", [bid, rel], stream, name=rel, by=uid)  # 48 giờ (khu work)
    return {"batch_id": bid, "name": rel, "size": doc["size"]}


def batch_files(kho: TenantFiles, bid: str) -> list[dict]:
    pre = f"tenants/{kho.tid}/work/{bid}/"
    return [{"name": d["key"][len(pre):], "size": d.get("size", 0), "by": d.get("by")} for d in kho.list("work", bid)]


# ====================================================================== GIAO BÀI
def send(db: Database, ctx: Ctx, ad: Any, *, batch_id: str, room_ids: list[str], device_ids: list[str], mode: str,
         dest: str, overwrite: bool) -> dict:
    store: Store = ad.store()
    bid = hexid(batch_id)
    files = [f["name"] for f in batch_files(store.kho, bid)] if bid else []
    if not files:
        raise LoiDich("Lô tệp không tồn tại hoặc đã quá 48 giờ — tải tệp lên lại")
    if msg := dest_bi_cam(dest):
        raise LoiDich(msg)
    tg, skipped = targets(db, ctx, ad, room_ids=room_ids, device_ids=device_ids, mode=mode)
    online = [d for d in tg if d.get("is_online")]
    deadline = min(SEND_MAX_S, SEND_BASE_S + SEND_PER_FILE_S * len(files))
    hosts = {norm_host(d["hostname"]): _info(d) for d in tg}
    sid = store.create_session("send", token=uuid.uuid4().hex, meta={  # TRƯỚC khi gửi (agent nhanh báo ngay)
        "total": len(online), "expected": [norm_host(d["hostname"]) for d in online], "hosts": hosts,
        "by_room": {}, "dest": dest, "dest_dir": dest_dir(dest), "files": files, "overwrite": overwrite,
        "batch_id": bid, "mode": mode, "by": ctx.username, "by_user_id": str(ctx.user_id),
        "limited": bool(ctx.room_ids) and not ctx.is_super, "started_at": _now_iso(), "deadline_s": deadline})
    cmd = {"action": "receive_work", "batch_id": bid, "files": files, "dest_folder": dest, "overwrite": overwrite,
           "session_id": sid, "report_url": "/send_report"}
    sent, sk = _dispatch(ad, tg, cmd)
    by_room: dict[str, list[str]] = {}
    for s in sent:
        if rid := hosts[s["hostname"]].get("room_id"):
            by_room.setdefault(rid, []).append(s["hostname"])
    store.update_meta("send", sid, {"total": len(sent), "expected": [s["hostname"] for s in sent], "by_room": by_room})
    # nhật ký mới bắt đầu sạch (như hub cũ)
    repo_for(db, ctx.tenant_id, "pushed_files").delete_many({"status": "deleted"})
    return {"session_id": sid, "total": len(sent), "sent": sent, "skipped": skipped + sk, "files": files,
            "dest_dir": dest_dir(dest), "deadline_s": deadline}


def send_status(ad: Any, sid: str, now: datetime | None = None) -> dict | None:
    data = ad.store().read(sid)
    if data is None or data["kind"] != "send":
        return None
    meta = data["meta"]
    elapsed = _elapsed(meta, now)
    late = elapsed > float(meta.get("deadline_s") or SEND_BASE_S)
    got = {r["hostname"]: r for r in data["results"]}
    rows = []
    for host in meta.get("expected", []):
        info = meta.get("hosts", {}).get(host, {})
        r = got.get(host)
        if r is None:
            rows.append({"hostname": host, "room_name": info.get("room_name", ""),
                         "status": "timeout" if late else "running"})
        else:
            rows.append({"hostname": host, "room_name": info.get("room_name", ""),
                         **{k: r.get(k) for k in ("status", "saved", "skipped", "failed", "reason", "files")}})
    finished = sum(1 for r in rows if r["status"] != "running")
    return {"session_id": data["token"], "started_at": meta["started_at"], "elapsed_s": round(elapsed, 1),
            "deadline_s": meta.get("deadline_s"), "total": len(rows), "finished": finished,
            "complete": finished == len(rows), "dest_dir": meta.get("dest_dir"), "files": meta.get("files", []),
            "overwrite": meta.get("overwrite"), "by": meta.get("by"), "results": rows,
            "_by_user_id": meta.get("by_user_id"), "_limited": meta.get("limited")}


def on_send_report(ad: Any, store: Store, sid: str, host: str, res: dict) -> int:
    """Móc từ `/send_report`: ghi sổ ĐÚNG các tệp agent báo đã ghi (bỏ tệp 'đã có, bỏ qua'). Trả số tệp ghi sổ."""
    sess = store.session("send", sid)
    info = (sess or {}).get("meta", {}).get("hosts", {}).get(norm_host(host))
    if sess is None or info is None:
        return 0
    meta = sess["meta"]
    now = datetime.now(UTC)
    items = []
    for f in res.get("files") or []:
        if not f.get("ok") or f.get("note"):
            continue
        rel = str(f.get("name") or "")
        if not rel:
            continue
        fp = full_path(meta["dest_dir"], rel)
        items.append(({"hostname": info["hostname"], "full_path": fp}, {"$set": {
            "device_id": info.get("device_id"), "room_id": info.get("room_id"), "room_name": info.get("room_name"),
            "folder": fp.rsplit("\\", 1)[0], "filename": rel.replace("/", "\\"), "batch_id": meta.get("batch_id"),
            "session_id": sid, "status": "pushed", "pushed_at": now, "by": meta.get("by")},
            "$setOnInsert": {"created_at": now}}))
    repo_for(store.results.db, store.tid, "pushed_files").bulk_upsert(items)
    return len(items)


# ====================================================================== tệp đã giao: nhật ký + xoá (hàng chờ khi tắt)
def _scope_rooms(ctx: Ctx) -> dict:
    if ctx.is_super or not ctx.room_ids:
        return {}
    return {"room_id": {"$in": [str(r) for r in ctx.room_ids]}}


def pushed_list(db: Database, ctx: Ctx, ad: Any) -> list[dict]:
    live = devices._live(ad, ctx)  # noqa: SLF001 — cùng hệ thống
    out = []
    for r in repo_for(db, ctx.tenant_id, "pushed_files").find(_scope_rooms(ctx)):
        out.append({"hostname": r.get("hostname"), "room_name": r.get("room_name") or "", "folder": r.get("folder"),
                    "filename": r.get("filename"), "status": r.get("status") or "pushed",
                    "pushed_at": r["pushed_at"].isoformat() if isinstance(r.get("pushed_at"), datetime) else None,
                    "online": bool(live and live.state.is_online(r.get("hostname") or ""))})
    return sorted(out, key=lambda x: (x["room_name"], x["hostname"] or "", x["filename"] or ""))


def _xoa(ad: Any, host: str, fp: str) -> bool:
    """Lệnh xoá VĨNH VIỄN (như hub cũ: agent os.remove/rmtree, không vào Thùng rác); không chờ trả lời."""
    return ad.send_fs_request(host, {"op": "delete", "req_id": "del_" + uuid.uuid4().hex, "target": fp}, "")


def delete_pushed(db: Database, ctx: Ctx, ad: Any, room_ids: list[str] | None = None) -> dict:
    repo = repo_for(db, ctx.tenant_id, "pushed_files")
    q: dict = {**_scope_rooms(ctx), "status": {"$in": ["pushed", "pending"]}}
    if room_ids:
        allowed = q.get("room_id", {}).get("$in")
        q["room_id"] = {"$in": [r for r in room_ids if allowed is None or r in allowed]}
    sent = kept = 0
    hosts: set[str] = set()
    now = datetime.now(UTC)
    for r in list(repo.find(q, {"hostname": 1, "full_path": 1})):
        if _xoa(ad, r["hostname"], r["full_path"]):
            repo.update_one({"_id": r["_id"]}, {"$set": {"status": "deleted", "deleted_at": now}})
            sent += 1
            hosts.add(r["hostname"])
        else:
            repo.update_one({"_id": r["_id"]}, {"$set": {"status": "pending"}})
            kept += 1
    if not sent and not kept:
        return {"deleted": 0, "kept": 0, "machines": 0, "message": "Chưa ghi nhận tệp đã giao nào."}
    msg = f"Đã gửi lệnh xoá {sent} tệp trên {len(hosts)} máy."
    if kept:
        msg += f" Còn {kept} tệp ở máy đang tắt — sẽ TỰ ĐỘNG xoá khi máy online lại."
    return {"deleted": sent, "kept": kept, "machines": len(hosts), "message": msg}


def start(app: Any, sio: Any) -> None:
    """Vòng nền xoá tệp chờ (hub cũ: pending_delete_worker 8 s) — gọi trong app.server.main."""
    from app.legacy_adapter.writer import run_forever

    ad = app.extensions["legacy"]
    sio.start_background_task(run_forever, lambda: flush_pending(ad), sio.sleep, 10.0, "xoá tệp chờ")


def flush_pending(ad: Any) -> int:
    """Vòng nền: tệp đang CHỜ XOÁ mà máy đã online lại → xoá nốt. Giành dòng trước khi gửi (mỗi tệp chỉ gửi 1 lần)."""
    tid = ad.tenant_id
    if tid is None:
        return 0
    repo = repo_for(ad.db, tid, "pushed_files")
    done = 0
    for r in list(repo.find({"status": "pending"}, {"hostname": 1, "full_path": 1}).limit(500)):
        if not ad.state.has_socket(norm_host(r["hostname"])):
            continue
        if repo.update_one({"_id": r["_id"], "status": "pending"},
                           {"$set": {"status": "deleted", "deleted_at": datetime.now(UTC)}}).modified_count != 1:
            continue
        if _xoa(ad, r["hostname"], r["full_path"]):
            done += 1
        else:  # socket vừa rớt → trả lại hàng chờ
            repo.update_one({"_id": r["_id"]}, {"$set": {"status": "pending"}})
    if done:
        log.info("Tự xoá %d tệp chờ-xoá trên máy vừa online", done)
    return done


# ====================================================================== THU BÀI
def _last_sent(store: Store, room_id: str, now: datetime) -> dict[str, dict]:
    """Máy đã NHẬN giao bài gần nhất (≤ 12 giờ) ở phòng → để thu bài biết máy nào thiếu (hub cũ: SENT_HOSTS, RAM)."""
    doc = store.results.find_one({"kind": "send", "role": "session", f"meta.by_room.{room_id}": {"$exists": True},
                                  "created_at": {"$gte": now - SENT_WINDOW}}, sort=[("created_at", -1)])
    if not doc:
        return {}
    hosts = doc["meta"].get("hosts", {})
    return {h: hosts.get(h, {"hostname": h}) for h in doc["meta"]["by_room"].get(room_id, [])}


def collect(db: Database, ctx: Ctx, ad: Any, *, room_ids: list[str], device_ids: list[str], mode: str, src: str,
            patterns: list[str], delete_after: bool, save_thu: bool, ca: str) -> dict:
    store: Store = ad.store()
    if msg := nguon_bi_cam(src, delete_after):
        raise LoiDich(msg)
    pats = mau_hop_le(patterns)
    tg, skipped = targets(db, ctx, ad, room_ids=room_ids, device_ids=device_ids, mode=mode)
    now = datetime.now(UTC)
    expected = {norm_host(d["hostname"]): _info(d) for d in tg if d.get("is_online")}
    for rid in room_ids:  # máy đã nhận giao bài mà nay tắt → vẫn phải hiện "chưa nộp"
        for h, info in _last_sent(store, rid, now).items():
            gv = is_teacher_pc(h)
            if (mode == "students" and gv) or (mode == "teachers" and not gv):
                continue
            expected.setdefault(h, info)
    ca_n = norm_ca(ca) or ("Ca sáng" if datetime.now().hour < 12 else "Ca chiều")
    sid = store.create_session("collect", token=uuid.uuid4().hex, meta={
        "total": len(expected), "expected": list(expected.values()), "targeted": [], "dispatched": False,
        "src": src, "patterns": pats, "delete_after": delete_after, "save_thu": save_thu, "ca": ca_n,
        "mode": mode, "by": ctx.username, "by_user_id": str(ctx.user_id),
        "limited": bool(ctx.room_ids) and not ctx.is_super, "started_at": _now_iso(),
        "deadline_s": COLLECT_DEADLINE_S})
    cmd = {"action": "collect_work", "session_id": sid, "src_folder": src, "patterns": pats,
           "upload_url": "/collect_upload", "delete_after": delete_after}
    sent, sk = _dispatch(ad, tg, cmd)
    store.update_meta("collect", sid, {"targeted": [s["hostname"] for s in sent], "dispatched": True})
    return {"session_id": sid, "expected": len(expected), "total": len(sent), "sent": sent, "skipped": skipped + sk,
            "ca": ca_n, "deadline_s": COLLECT_DEADLINE_S}


def collect_status(ad: Any, sid: str, now: datetime | None = None) -> dict | None:
    data = ad.store().read(sid)
    if data is None or data["kind"] != "collect":
        return None
    meta = data["meta"]
    elapsed = _elapsed(meta, now)
    late = elapsed > float(meta.get("deadline_s") or COLLECT_DEADLINE_S)
    targeted = set(meta.get("targeted") or [])
    got = {r["hostname"]: r for r in data["results"]}
    infos = {e["hostname"]: e for e in meta.get("expected", [])}
    for h in got:  # máy nộp mà không nằm trong danh sách kỳ vọng (vd. agent đổi tên) — vẫn hiện
        infos.setdefault(h, {"hostname": h, "room_name": ad.room_of(h)})
    rows = []
    for host, info in infos.items():
        r = got.get(host, {})
        st = r.get("status")
        if not st:
            if r.get("uploaded"):
                st = "ok"  # agent nộp xong, báo cáo đang tới (hoặc agent rất cũ không báo) — như rowsFromCollect hệ cũ
            elif meta.get("dispatched") and host not in targeted:
                st = "offline"
            else:
                st = "offline" if late else "running"
        rows.append({"hostname": host, "room_name": info.get("room_name") or "", "status": st,
                     "files": r.get("files") or [], "count": r.get("count") or len(r.get("files") or []),
                     "deleted": bool(r.get("deleted")), "error": r.get("error") or "", "size": r.get("size"),
                     "has_zip": bool(r.get("uploaded")), "saved_dir": r.get("saved_dir") or "",
                     "saved_error": r.get("saved_error") or ""})
    rows.sort(key=lambda x: (x["room_name"], x["hostname"]))
    running = sum(1 for r in rows if r["status"] == "running")
    return {"session_id": data["token"], "started_at": meta["started_at"], "elapsed_s": round(elapsed, 1),
            "deadline_s": meta.get("deadline_s"), "ca": meta.get("ca"), "src": meta.get("src"),
            "patterns": meta.get("patterns"), "delete_after": meta.get("delete_after"),
            "save_thu": meta.get("save_thu"), "by": meta.get("by"), "total": len(rows),
            "submitted": sum(1 for r in rows if r["has_zip"]),
            "complete": running == 0 and bool(meta.get("dispatched")),
            "results": rows, "_by_user_id": meta.get("by_user_id"), "_limited": meta.get("limited")}


# ---------------------------------------------------------------------- tải bài đã thu
def zip_doc(store: Store, sid: str, host: str) -> dict | None:
    r = store.results.find_one({"token": hexid(sid), "kind": "collect", "role": "result", "hostname": norm_host(host)})
    if not r or not r.get("zip"):
        return None
    try:
        return store.kho.get(store.kho.key("collected", hexid(sid), r["zip"]))
    except KhoaSai:
        return None


def _open_zip_src(kho: TenantFiles, key: str) -> IO[bytes]:
    p = kho.local_path(key)
    if p is not None:
        return open(p, "rb")  # noqa: SIM115 — nơi gọi đóng
    tmp = tempfile.TemporaryFile()
    with kho.open(key) as f:
        shutil.copyfileobj(f, tmp, CHUNK)
    tmp.seek(0)
    return tmp


def entries(store: Store, sid: str, host: str) -> list[dict] | None:
    doc = zip_doc(store, sid, host)
    if doc is None:
        return None
    with _open_zip_src(store.kho, doc["key"]) as src, zipfile.ZipFile(src) as z:
        return [{"path": "/".join(safe_parts(i.filename)), "size": i.file_size} for i in z.infolist() if not i.is_dir()]


def entry_stream(store: Store, sid: str, host: str, path: str) -> tuple[str, int, Iterator[bytes]] | None:
    """(tên tệp, cỡ, luồng) của MỘT tệp trong bài thu — để Desktop lưu thẳng vào <thư mục>/<phòng>/<máy>/…"""
    doc = zip_doc(store, sid, host)
    if doc is None:
        return None
    src = _open_zip_src(store.kho, doc["key"])
    z = zipfile.ZipFile(src)
    info = next((i for i in z.infolist() if not i.is_dir() and "/".join(safe_parts(i.filename)) == path), None)
    if info is None:
        z.close()
        src.close()
        return None

    def gen() -> Iterator[bytes]:
        try:
            with z.open(info) as f:
                while chunk := f.read(CHUNK):
                    yield chunk
        finally:
            z.close()
            src.close()

    return path.rsplit("/", 1)[-1], info.file_size, gen()


def zip_all(store: Store, st: dict) -> IO[bytes] | None:
    """Gói MỌI bài đã nộp: `<Phòng>/<Máy>.zip` (ZIP_STORED — bên trong đã nén; ghi luồng ra tệp tạm, không vào RAM)."""
    tmp = tempfile.TemporaryFile()
    n = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for r in st["results"]:
            doc = zip_doc(store, st["session_id"], r["hostname"]) if r["has_zip"] else None
            if doc is None:
                continue
            arc = f"{safe_segment(r['room_name'] or 'Khac')}/{safe_segment(r['hostname'] + '.zip')}"
            with store.kho.open(doc["key"]) as f, z.open(arc, "w", force_zip64=True) as w:
                shutil.copyfileobj(f, w, CHUNK)
            n += 1
    if not n:
        tmp.close()
        return None
    tmp.seek(0)
    return tmp


# ---------------------------------------------------------------------- móc từ /collect_upload: lưu cấu trúc THU
def on_collect_upload(ad: Any, store: Store, sid: str, host: str, zip_key: str) -> str:
    """Phiên bật "lưu trên máy chủ": giải nén bản sao vào `thu/<Ca>/<Phòng>/<Máy>/` (chỉ giữ bản MỚI NHẤT; gói rỗng
    bỏ qua — không sinh thư mục rỗng; như _maybe_save_to_thu hệ cũ). Trả thư mục đã lưu ('' nếu không lưu)."""
    sess = store.session("collect", sid)
    meta = (sess or {}).get("meta", {})
    if not meta.get("save_thu"):
        return ""
    host = norm_host(host)
    info = {e["hostname"]: e for e in meta.get("expected", [])}.get(host, {})
    room = info.get("room_name") or ad.room_of(host)
    segs = [safe_segment(meta.get("ca") or "Ca sáng"), safe_segment(room or "Khác"), safe_segment(host)]
    kho = store.kho
    with _open_zip_src(kho, zip_key) as src, zipfile.ZipFile(src) as z:
        members = [i for i in z.infolist() if not i.is_dir()]
        if not members:
            return ""
        kho.delete_under("thu", *segs)
        for i in members:
            with z.open(i) as f:
                kho.save("thu", [*segs, *safe_parts(i.filename)], f, by=f"agent:{host}")
    saved = "/".join(segs)
    store.put_result("collect", sid, host, {"saved_dir": saved})
    return saved
