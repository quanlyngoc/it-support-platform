"""Sự cố (collection `incidents`) — Sổ tay 4.6 (xem) + 8.2 (quy trình xử lý phiếu).

Hai NGUỒN (`source`):
- `USER` — người dùng bấm "Báo hỏng" một máy (hệ cũ `/report_issue`). Mỗi máy chỉ có MỘT phiếu USER đang mở: báo
  tiếp khi phiếu còn mở = BỔ SUNG một dòng vào phiếu đó (giao diện hệ cũ cũng chỉ cho "+" khi máy đã có lỗi chờ xử lý).
- `SYSTEM_WATCHDOG` — bộ ghi nền tự phát hiện RAM / ổ cứng đổi, hết pin CMOS (legacy_adapter/hardware.py). Không bổ sung
  được; xử lý một lần là xong cả phiếu (như hệ cũ).

Phiếu USER lưu DÒNG có cấu trúc `items: [{n, text, at, by, done, done_at, done_by}]` thay cho chuỗi
"1. dd/mm/yy HH:MM. nội dung" + hậu tố " V" của hệ cũ; ghi chú IT `it_notes: [{lines, text, at, by}]`. `description`
vẫn giữ bản DỰNG SẴN dạng chữ như hệ cũ (tìm kiếm, xuất Excel, cảnh báo). Trạng thái: PENDING → (xử lý một phần / ghi
chú IT) PROCESSING → (mọi dòng xong) DONE — đúng luật `/resolve_issue` hệ cũ.

Chống ghi đè: mỗi phiếu có `rev`; cập nhật đọc-sửa-ghi chỉ ăn khi `rev` chưa đổi (hai IT cùng tick dòng → người sau
thử lại trên dữ liệu mới, không ai mất thao tác).

Sự cố lưu `room_name` (tên phòng lúc tạo — như hệ cũ; Chuyển phòng cập nhật lại). Người bị giới hạn phòng chỉ thấy / báo
sự cố của các phòng mình.
"""
from __future__ import annotations

from datetime import UTC, datetime
from re import escape
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.devices import service as devsvc
from app.realtime.hub import DESKTOP_NS, socketio
from app.tenants.context import Ctx
from app.tenants.repo import repo_for

DANG_MO = ("PENDING", "PROCESSING")
PHAN_CUNG = ("hardware_ram", "hardware_disk", "cmos")  # do bộ ghi tự phát hiện (hardware.py)
USER, SYSTEM = "USER", "SYSTEM_WATCHDOG"
MAX_TEXT = 1000
_TEXT = ("hostname", "room_name", "title", "description", "category", "status", "source", "reporter_name",
         "resolver_name")
_RETRY = 3
_MOI_NHAT = [("created_at", -1), ("_id", -1)]  # cùng mili-giây (CSDL làm tròn) → ObjectId tạo sau đứng trước


class LoiSuCo(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


def _oid(s: object) -> ObjectId | None:
    try:
        return ObjectId(str(s))
    except Exception:
        return None


def _scope(db: Database, ctx: Ctx) -> dict:
    if ctx.is_super or not ctx.room_ids:
        return {}
    names = [r["name"] for r in repo_for(db, ctx.tenant_id, "rooms").find({"_id": {"$in": list(ctx.room_ids)}},
                                                                          {"name": 1})]
    return {"room_name": {"$in": names}}


def _iso(v: object) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else None


def stamp(v: object) -> str:
    """Mốc giờ kiểu hệ cũ "dd/mm/yy HH:MM" theo giờ máy chủ (dữ liệu lưu UTC)."""
    if not isinstance(v, datetime):
        return ""
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone().strftime("%d/%m/%y %H:%M")


def render_items(items: list[dict]) -> str:
    return "\n".join(f"{it['n']}. {stamp(it.get('at'))}. {it.get('text') or ''}" for it in items)


def render_notes(notes: list[dict]) -> str:
    out = []
    for nt in notes:
        dong = f"Dòng {', '.join(str(n) for n in nt['lines'])} — " if nt.get("lines") else ""
        out.append(f"{dong}{stamp(nt.get('at'))} ({nt.get('by') or '?'}): {nt.get('text') or ''}")
    return "\n".join(out)


def public(doc: dict) -> dict:
    out: dict[str, Any] = {"id": str(doc["_id"])}
    for k in _TEXT:
        if doc.get(k) is not None:
            out[k] = doc[k]
    if doc.get("device_id") is not None:
        out["device_id"] = str(doc["device_id"])
    for k in ("created_at", "updated_at", "resolved_at"):
        if isinstance(doc.get(k), datetime):
            out[k] = doc[k].isoformat()
    if "items" in doc:
        out["items"] = [{"n": it["n"], "text": it.get("text") or "", "at": _iso(it.get("at")), "by": it.get("by") or "",
                         "done": bool(it.get("done")), "done_at": _iso(it.get("done_at")),
                         "done_by": it.get("done_by") or ""} for it in doc["items"]]
    out["it_notes"] = [{"lines": list(nt.get("lines") or []), "text": nt.get("text") or "", "at": _iso(nt.get("at")),
                        "by": nt.get("by") or ""} for nt in doc.get("it_notes") or []]
    out["rev"] = int(doc.get("rev") or 0)
    return out


# ====================================================================== xem
def list_incidents(db: Database, ctx: Ctx, *, status: str | None = None, q: str | None = None,
                   hostname: str | None = None, room_id: str | None = None, source: str | None = None,
                   since: datetime | None = None, until: datetime | None = None, limit: int = 200) -> list[dict]:
    return [public(d) for d in find_docs(db, ctx, status=status, q=q, hostname=hostname, room_id=room_id, source=source,
                                     since=since, until=until, limit=limit)]


def find_docs(db: Database, ctx: Ctx, *, status: str | None = None, q: str | None = None, hostname: str | None = None,
          room_id: str | None = None, source: str | None = None, since: datetime | None = None,
          until: datetime | None = None, limit: int = 200) -> list[dict]:
    query: dict = dict(_scope(db, ctx))
    if room_id:
        rid = _oid(room_id)
        if rid is None:
            return []
        if not ctx.is_super and ctx.room_ids and rid not in ctx.room_ids:
            return []
        r = repo_for(db, ctx.tenant_id, "rooms").find_one({"_id": rid}, {"name": 1})
        if r is None:
            return []
        query["room_name"] = r["name"]  # sự cố lưu tên phòng lúc tạo (Chuyển phòng cập nhật lại tên — devices.move)
    if hostname:
        query["hostname"] = {"$regex": f"^{escape(hostname.strip())}$", "$options": "i"}
    if status == "OPEN":
        query["status"] = {"$in": list(DANG_MO)}
    elif status:
        query["status"] = status
    if source:
        query["source"] = source
    if since or until:
        query["created_at"] = {**({"$gte": since} if since else {}), **({"$lt": until} if until else {})}
    if q:
        rx = {"$regex": escape(q.strip()), "$options": "i"}
        query["$or"] = [{k: rx} for k in ("hostname", "title", "room_name", "description", "reporter_name",
                                         "resolver_name")]
    cur = repo_for(db, ctx.tenant_id, "incidents").find(query, {"tenant_id": 0}).sort(_MOI_NHAT).limit(limit)
    return list(cur)


def summary(db: Database, ctx: Ctx) -> dict:
    """Số phiếu đang mở theo trạng thái + số cảnh báo phần cứng đang mở — số TUYỆT ĐỐI tính lại mỗi lần hỏi."""
    match = {**_scope(db, ctx), "status": {"$in": list(DANG_MO)}}
    pending = processing = hardware = 0
    for r in repo_for(db, ctx.tenant_id, "incidents").aggregate([
            {"$match": match}, {"$group": {"_id": {"s": "$status", "c": "$category"}, "n": {"$sum": 1}}}]):
        n = r["n"]
        if r["_id"].get("s") == "PENDING":
            pending += n
        else:
            processing += n
        if r["_id"].get("c") in PHAN_CUNG:
            hardware += n
    return {"open": pending + processing, "pending": pending, "processing": processing, "hardware_open": hardware}


def get(db: Database, ctx: Ctx, incident_id: str) -> dict:
    iid = _oid(incident_id)
    doc = repo_for(db, ctx.tenant_id, "incidents").find_one({"_id": iid, **_scope(db, ctx)}) if iid else None
    if doc is None:
        raise LoiSuCo("Không có sự cố này hoặc ngoài phạm vi được giao", 404)
    return doc


# ====================================================================== realtime
def _emit(ctx: Ctx, doc: dict, action: str) -> None:
    """`incident_update` (tên sự kiện của hệ cũ) — tới người không giới hạn phòng + người đang xem đúng phòng đó; hệ
    cũ broadcast cho mọi trình duyệt."""
    payload = {"action": action, "id": str(doc["_id"]), "hostname": doc.get("hostname") or "",
               "room_name": doc.get("room_name") or "", "status": doc.get("status") or ""}
    rooms = [f"t:{ctx.tenant_id}:incidents"]
    if doc.get("room_id"):
        rooms.append(f"t:{ctx.tenant_id}:room:{doc['room_id']}")
    for room in rooms:
        socketio.emit("incident_update", payload, to=room, namespace=DESKTOP_NS)


def _clean(text: str) -> str:
    t = " ".join((text or "").split())[:MAX_TEXT]  # một dòng: xuống dòng sẽ phá cách đánh số dòng
    if not t:
        raise LoiSuCo("Chưa nhập nội dung")
    return t


def _save(db: Database, ctx: Ctx, iid: ObjectId, build) -> dict:
    """Đọc → `build(doc)` trả bản cập nhật → ghi CHỈ KHI `rev` chưa đổi; đổi thì đọc lại và làm lại (≤ 3 lần)."""
    repo = repo_for(db, ctx.tenant_id, "incidents")
    for _ in range(_RETRY):
        doc = repo.find_one({"_id": iid, **_scope(db, ctx)})
        if doc is None:
            raise LoiSuCo("Không có sự cố này hoặc ngoài phạm vi được giao", 404)
        upd = build(doc)
        rev = doc.get("rev")
        cond: dict = {"_id": iid, "rev": rev} if rev is not None else {"_id": iid, "rev": {"$exists": False}}
        upd.setdefault("$inc", {})["rev"] = 1
        if repo.update_one(cond, upd).matched_count:
            new = repo.find_one({"_id": iid})
            assert new is not None
            return new
    raise LoiSuCo("Sự cố vừa được người khác cập nhật — tải lại rồi thử lại", 409)


# ====================================================================== báo hỏng / bổ sung (mọi người trong phạm vi)
def create(db: Database, ctx: Ctx, device_id: str, text: str, *, alert=None) -> tuple[dict, bool]:
    """Báo hỏng một máy. Máy đã có phiếu USER đang mở → bổ sung dòng vào phiếu đó (trả appended=True).
    `alert(hostname, room, source, description)` = gửi cảnh báo (chỉ khi tạo phiếu MỚI, như hệ cũ)."""
    text = _clean(text)
    did = _oid(device_id)
    dev = repo_for(db, ctx.tenant_id, "computers").find_one({"_id": did, **devsvc._scope(ctx)}) if did else None
    if dev is None:
        raise LoiSuCo("Không có máy này hoặc ngoài phạm vi được giao", 404)
    host = devsvc._host(dev)
    repo = repo_for(db, ctx.tenant_id, "incidents")
    cu = repo.find_one({"hostname": host, "source": USER, "status": {"$in": list(DANG_MO)}}, {"_id": 1},
                       sort=[("created_at", -1)])
    if cu is not None:
        return append(db, ctx, str(cu["_id"]), text), True
    now = datetime.now(UTC)
    items = [{"n": 1, "text": text, "at": now, "by": ctx.username, "done": False}]
    doc = {"hostname": host, "device_id": dev["_id"], "room_name": str(dev.get("room_name") or ""),
           "room_id": dev.get("room_id"), "title": text[:120], "category": "user", "status": "PENDING", "source": USER,
           "reporter_name": ctx.username, "reporter_id": ctx.user_id, "items": items, "it_notes": [],
           "description": render_items(items), "created_at": now, "updated_at": now, "rev": 1}
    doc["_id"] = repo.insert_one(doc).inserted_id
    _emit(ctx, doc, "new")
    if alert is not None:
        alert(host, doc["room_name"], ctx.username, doc["description"])
    return doc, False


def append(db: Database, ctx: Ctx, incident_id: str, text: str) -> dict:
    text = _clean(text)
    iid = _oid(incident_id)
    if iid is None:
        raise LoiSuCo("Không có sự cố này", 404)

    def build(doc: dict) -> dict:
        if doc.get("source") != USER:
            raise LoiSuCo("Sự cố phần cứng do hệ thống tự ghi — không bổ sung được", 409)
        if doc.get("status") not in DANG_MO:
            raise LoiSuCo("Sự cố đã xử lý xong — hãy báo hỏng mới", 409)
        items = list(doc.get("items") or [])
        now = datetime.now(UTC)
        items.append({"n": max((it["n"] for it in items), default=0) + 1, "text": text, "at": now, "by": ctx.username,
                      "done": False})
        return {"$set": {"items": items, "description": render_items(items), "updated_at": now}}

    doc = _save(db, ctx, iid, build)
    _emit(ctx, doc, "append")
    return doc


# ====================================================================== xử lý (quyền incident.handle)
def note(db: Database, ctx: Ctx, incident_id: str, text: str) -> dict:
    """Ghi chú IT KHÔNG đánh dấu dòng nào xong (vd. "đã nhận, chờ linh kiện") → phiếu chuyển ĐANG XỬ LÝ, người ghi là
    người xử lý."""
    text = _clean(text)
    iid = _oid(incident_id)
    if iid is None:
        raise LoiSuCo("Không có sự cố này", 404)

    def build(doc: dict) -> dict:
        if doc.get("status") not in DANG_MO:
            raise LoiSuCo("Sự cố đã xử lý xong", 409)
        now = datetime.now(UTC)
        return {"$set": {"status": "PROCESSING", "resolver_name": ctx.username, "resolver_id": ctx.user_id,
                         "updated_at": now},
                "$push": {"it_notes": {"lines": [], "text": text, "at": now, "by": ctx.username}}}

    doc = _save(db, ctx, iid, build)
    _emit(ctx, doc, "note")
    return doc


def resolve(db: Database, ctx: Ctx, incident_id: str, text: str, lines: list[int] | None = None) -> dict:
    """Xử lý (hệ cũ `/resolve_issue`): `lines` rỗng hoặc sự cố hệ thống → xong CẢ phiếu; có `lines` → chỉ các dòng đó
    xong, phiếu DONE khi mọi dòng đã xong, còn lại PROCESSING. Ghi chú IT bắt buộc."""
    text = _clean(text)
    iid = _oid(incident_id)
    if iid is None:
        raise LoiSuCo("Không có sự cố này", 404)
    chon = {int(n) for n in (lines or [])}

    def build(doc: dict) -> dict:
        if doc.get("status") not in DANG_MO:
            raise LoiSuCo("Sự cố đã xử lý xong", 409)
        now = datetime.now(UTC)
        items = [dict(it) for it in doc.get("items") or []]
        con = {it["n"] for it in items if not it.get("done")}
        if doc.get("source") != USER or not items or not chon:
            xong = con
        else:
            xong = chon & con
            if not xong:
                raise LoiSuCo("Các dòng đã chọn không còn dòng nào chờ xử lý")
        for it in items:
            if it["n"] in xong:
                it.update(done=True, done_at=now, done_by=ctx.username)
        status = "DONE" if all(it.get("done") for it in items) else "PROCESSING"
        s: dict = {"status": status, "resolver_name": ctx.username, "resolver_id": ctx.user_id, "updated_at": now}
        if items:
            s["items"] = items
        if status == "DONE":
            s["resolved_at"] = now
        return {"$set": s, "$push": {"it_notes": {"lines": sorted(xong), "text": text, "at": now,
                                                  "by": ctx.username}}}

    doc = _save(db, ctx, iid, build)
    _emit(ctx, doc, "resolve")
    return doc


# ====================================================================== log máy trạm (hệ cũ /api/get_client_logs)
def client_logs(db: Database, ctx: Ctx, *, hostname: str | None = None, q: str | None = None,
                limit: int = 100) -> list[dict]:
    query: dict = {}
    if not ctx.is_super and ctx.room_ids:  # log không lưu phòng → giới hạn theo các máy đang thuộc phòng được giao
        hosts = [devsvc._host(d) for d in repo_for(db, ctx.tenant_id, "computers").find(
            devsvc._scope(ctx), {"legacy_hostname": 1, "hostname": 1})]
        query["hostname"] = {"$in": hosts}
    if hostname:
        rx = {"$regex": f"^{escape(hostname.strip())}$", "$options": "i"}
        query["hostname"] = {**query["hostname"], **rx} if "hostname" in query else rx
    if q:
        rx = {"$regex": escape(q.strip()), "$options": "i"}
        query["$or"] = [{"context": rx}, {"error": rx}, {"hostname": rx}]
    out = []
    for d in repo_for(db, ctx.tenant_id, "client_logs").find(query, {"tenant_id": 0}).sort(_MOI_NHAT).limit(limit):
        out.append({"id": str(d["_id"]), "hostname": d.get("hostname") or "", "mac": d.get("mac") or "",
                    "ip": d.get("ip") or "", "context": d.get("context") or "", "error": d.get("error") or "",
                    "created_at": _iso(d.get("created_at"))})
    return out
