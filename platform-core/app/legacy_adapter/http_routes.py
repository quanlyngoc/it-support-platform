"""Route HTTP agent v2 gọi (HOP_DONG mục C). Đường dẫn đặt ở GỐC (không /api) đúng như hub cũ để Caddy canary chỉ
cần đổi đích, agent không phải sửa gì.

`/update` và `/check_command/<mac>` (≈ 95% lưu lượng) KHÔNG nằm ở đây mà ở đường nhanh WSGI `fastpath.py`
(logic: LegacyAdapter.handle_update / handle_check_command). LUẬT SỐNG CÒN: `/update` luôn 200 (A1), không bao giờ 426
(A2), máy mất socket → `reconnect_socket` (A3); `/check_update` luôn 200 + khoá `version` (A4).
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from apiflask import APIBlueprint
from flask import current_app, g, request, send_file, send_from_directory
from werkzeug.exceptions import NotFound

from app.legacy_adapter.adapter import LegacyAdapter
from app.legacy_adapter.identity import mac12, norm_host, norm_mac
from app.legacy_adapter.store import clip, hexid, safe_host, safe_name
from app.legacy_adapter.update_gate import CLOSED, DL_HOLD, DL_MAX, INSTALLER
from app.tenants.repo import repo_for

log = logging.getLogger("legacy.http")
bp = APIBlueprint("legacy_v2", __name__, enable_openapi=False)

OK = {"status": "success"}
_NO_TENANT = ({"status": "error", "message": "Core chưa gắn tổ chức cho agent v2"}, 503)
_last_err = [0.0]


def _ad() -> LegacyAdapter:
    return current_app.extensions["legacy"]


def _json() -> dict:
    d = request.get_json(silent=True, force=True)
    return d if isinstance(d, dict) else {}


def _log_rare(msg: str) -> None:
    """Lỗi trên đường nóng: ghi tối đa 1 dòng/60 s (≈ 440 nhịp tim/s — không để nhật ký phình như server.log cũ)."""
    now = time.monotonic()
    if now - _last_err[0] >= 60:
        _last_err[0] = now
        log.exception(msg)


@bp.before_request
def _ip_gate():
    if not _ad().ip_ok(g.client_ip):
        return {"status": "error", "message": "IP không thuộc dải agent"}, 403
    return None


# ====================================================================== cập nhật agent
@bp.get("/check_update")
def check_update():
    try:
        ad = _ad()
        host = ad.state.host_for_ip(g.client_ip)
        return ad.gate.decide(g.client_ip, host, ad.room_of(host) if host else "")
    except Exception:
        _log_rare("Lỗi /check_update (trả 'không có bản mới')")
        return dict(CLOSED)


@bp.get("/download_setup")
def download_setup():
    ad = _ad()
    if not ad.state.dl_acquire(DL_MAX, DL_HOLD):
        return "busy", 503  # agent tự thử lại chu kỳ sau
    if not ad.gate.manifest():
        return "File not found", 404  # không có bộ cài khớp manifest → không phát (A5)
    return send_file(ad.gate.installer, as_attachment=True, download_name=INSTALLER, max_age=0)


@bp.post("/client_log")
def client_log():
    d = _json()
    ad = _ad()
    tid = ad.tenant_id
    if tid:
        try:
            repo_for(ad.db, tid, "client_logs").insert_one({
                "mac": norm_mac(d.get("mac")) or str(d.get("mac") or "")[:40],
                "hostname": str(d.get("hostname") or "")[:80], "context": str(d.get("context") or "")[:200],
                "error": str(d.get("error") or "")[:4000], "ip": g.client_ip, "created_at": datetime.now(UTC)})
        except Exception:
            _log_rare("Không ghi được client_log")
    return OK


@bp.post("/offline")
def offline():
    ad = _ad()
    host = norm_host(_json().get("hostname"))
    if host:
        ad.state.tat_sach[host] = ad.state.clock()  # mốc "tắt có chủ ý" cho hệ thi (TAT_SACH)
        ad.state.mark_offline(host, "tat_may")
        log.info("OFFLINE %s vừa tắt (tín hiệu từ agent)", host)
    return OK


# ====================================================================== kết quả đăng nhập / terminal
def _auth_result(kind: str, event: str, key: str):
    ad = _ad()
    d = _json()
    mac = norm_mac(key) or (ad.state.hosts[h].mac if (h := norm_host(key)) in ad.state.hosts else "")
    out = {"mac": mac or key, "status": d.get("status"), "msg": str(d.get("msg") or "")[:500]}
    if kind == "login":
        out["hostname"] = str(d.get("hostname") or "")[:80]
    if kind == "ps_auth":
        out["pty_mode"] = bool(d.get("pty_mode", False))
    store = ad.store()
    if store is None:
        return _NO_TENANT
    store.put_event(kind, mac12(mac) or hexid(key) or str(key)[:80], out)
    if mac:
        ad.emit(event, out, ad.room_dev("watch" if kind == "login" else kind.split("_")[0], mac))
        if kind == "login" and (room := ad.login_room(mac)):
            ad.emit(event, out, room)  # về ĐÚNG người đã bấm đăng nhập từ xa (Sổ tay 6.2)
    return {"status": "ok"}


@bp.post("/login_result/<key>")
def login_result(key: str):
    return _auth_result("login", "login_response", key)


@bp.post("/ps_auth_result/<mac>")
def ps_auth_result(mac: str):
    return _auth_result("ps_auth", "ps_auth_response", mac)


@bp.post("/pty_auth_result/<mac>")
def pty_auth_result(mac: str):
    return _auth_result("pty_auth", "pty_auth_response", mac)


@bp.post("/ps_bulk_result/<token>")
def ps_bulk_result(token: str):
    ad = _ad()
    d = _json()
    host = norm_host(d.get("hostname"))
    store = ad.store()
    if store is None or not host or store.session("ps_bulk", token) is None:
        return {"status": "ignored"}  # vẫn 200 như hub cũ
    res = {"hostname": host, "status": str(d.get("status") or "done")[:16], "exit_code": d.get("exit_code"),
           "stdout": clip(d.get("stdout")), "stderr": clip(d.get("stderr"))}
    done = store.put_result("ps_bulk", token, host, res)
    ad.emit("ps_bulk_result", {"token": hexid(token), "result": res, "done_count": done}, ad.room_res(hexid(token)))
    return {"status": "ok"}


# ====================================================================== giao bài / thu bài
@bp.post("/send_report")
def send_report():
    ad = _ad()
    d = _json()
    store = ad.store()
    sid = hexid(d.get("session_id"))
    if store is not None and store.session("send", sid) is not None:
        files = [{"name": str(f.get("name", ""))[:200], "ok": bool(f.get("ok")), "error": str(f.get("error", ""))[:200],
                  "note": str(f.get("note", ""))[:100]} for f in (d.get("files") or []) if isinstance(f, dict)][:500]
        res = {"status": str(d.get("status", "fail"))[:16], "saved": _int(d.get("saved")),
               "skipped": _int(d.get("skipped")), "failed": _int(d.get("failed")),
               "reason": str(d.get("reason", ""))[:200], "files": files}
        done = store.put_result("send", sid, str(d.get("hostname") or "?"), res)
        ad.emit("send_report", {"session_id": sid, "hostname": norm_host(d.get("hostname")), "result": res,
                                "done_count": done}, ad.room_res(sid))
    return {"status": "ok"}  # hub cũ luôn ok kể cả phiên lạ


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


@bp.get("/work_file/<batch_id>/<path:filename>")
def work_file(batch_id: str, filename: str):
    ad = _ad()
    bid = hexid(batch_id)
    base = ad.root / "work" / bid
    if not bid or not base.is_dir():
        return {"status": "error"}, 404
    try:
        return send_from_directory(base, filename, as_attachment=True, max_age=0)
    except NotFound:
        return {"status": "error"}, 404


@bp.post("/collect_upload")
def collect_upload():
    ad = _ad()
    store = ad.store()
    sid = hexid(request.form.get("session_id"))
    if store is None or not sid or store.session("collect", sid) is None:
        return {"status": "error", "message": "Phiên thu không tồn tại"}, 404
    f = request.files.get("file")
    if not f:
        return {"status": "error", "message": "Không có tệp"}, 400
    host = safe_host(request.form.get("hostname"))
    dest = store.dir("collect", sid) / f"{host}.zip"
    f.save(dest)
    store.put_result("collect", sid, host, {"uploaded": True, "size": dest.stat().st_size, "zip": dest.name})
    ad.emit("collect_upload", {"session_id": sid, "hostname": norm_host(host), "size": dest.stat().st_size},
            ad.room_res(sid))
    return {"status": "ok"}


@bp.post("/collect_report")
def collect_report():
    ad = _ad()
    d = _json()
    store = ad.store()
    sid = hexid(d.get("session_id"))
    if store is None or not sid or store.session("collect", sid) is None:
        return {"status": "error", "message": "Phiên thu không tồn tại"}, 404
    files = [str(x)[:200] for x in (d.get("files") or [])][:500]
    res = {"status": str(d.get("status") or "fail")[:16], "files": files, "count": len(files),
           "deleted": bool(d.get("deleted")), "error": str(d.get("error") or "")[:300]}
    host = safe_host(d.get("hostname"))
    store.put_result("collect", sid, host, res)
    ad.emit("collect_report", {"session_id": sid, "hostname": norm_host(host), "result": res}, ad.room_res(sid))
    return {"status": "ok"}


# ====================================================================== truyền tệp (trình duyệt 2 khung)
def _fs_save(token: str, name: str, writer):
    ad = _ad()
    store = ad.store()
    if store is None:
        return _NO_TENANT
    tok = hexid(token)
    if not tok or store.fs_token(tok) is None:
        return {"status": "error", "message": "token sai/hết hạn"}, 403
    dest = store.dir("fs_tmp") / f"{tok}_{safe_name(name)}"
    writer(dest)
    store.fs_set(tok, "pull_path", dest)
    return {"status": "ok"}


@bp.post("/fs_recv")
def fs_recv():
    f = request.files.get("file")
    tok = request.form.get("token")
    if not hexid(tok) or not f:
        return {"status": "error"}, 400
    return _fs_save(str(tok), f.filename or "file", f.save)


@bp.post("/fs_recv_raw")
def fs_recv_raw():
    def write(dest):
        with open(dest, "wb") as out:
            while chunk := request.stream.read(262144):  # luồng thô 256 KB/khối — không nạp cả tệp vào RAM
                out.write(chunk)
    return _fs_save(request.args.get("token", ""), request.args.get("name", ""), write)


def _fs_send(token: str, field: str, missing: dict):
    ad = _ad()
    store = ad.store()
    if store is None:
        return _NO_TENANT
    doc = store.fs_token(token)
    if doc is None:
        return {"status": "error"}, 403
    p = store.existing(doc, field)
    if p is None:
        return missing, 404
    return send_file(p, as_attachment=True, download_name=p.name.split("_", 1)[-1], max_age=0)


@bp.get("/fs_serve/<token>")
def fs_serve(token: str):
    return _fs_send(token, "push_path", {"status": "error"})


@bp.get("/fs_bridge/<token>")
def fs_bridge(token: str):
    return _fs_send(token, "pull_path", {"status": "pending"})
