"""API trình quản lý tệp 2 khung (Sổ tay 7.2). Lệnh tới máy trạm vẫn đi socket `/desktop` (`fs_request`, Core gắn
`reply_sid`); BYTES đi HTTP qua kho tệp chung (7.1) — không qua socket, không nạp cả tệp vào RAM.

Đối chiếu hệ cũ: `/fs_token` → `POST /api/files/token` · `/fs_get/<t>` → `GET /api/files/pulled/<t>` · `/fs_put` →
`POST /api/files/upload` · `/api/fs/whoami` → `GET /api/files/whoami` · `/api/fs/srv` (+ `srv_download`/`srv_upload`) →
`/api/files/srv*` nhưng "Máy chủ" là KHO RIÊNG của tổ chức (files/drive.py), không phải ổ đĩa thật.
Agent v2 không đổi gì: vẫn `/fs_recv_raw`, `/fs_serve/<t>`, `/fs_bridge/<t>` (legacy_adapter/http_routes.py).
"""
from __future__ import annotations

from typing import Any, Literal

from apiflask import APIBlueprint, abort
from flask import current_app, g, request, send_file
from pydantic import BaseModel, Field

from app.devices import service as devices
from app.files.drive import Drive, LoiKho
from app.legacy_adapter.store import Store
from app.rbac.perms import require_perm
from app.storage import TenantFiles, files_for, safe_segment
from app.tenants.context import current

bp = APIBlueprint("files", __name__, url_prefix="/api/files", tag="Trình quản lý tệp")


def _uid() -> str:
    return str(current().user_id)


def _store() -> Store:
    ad = devices._live(current_app.extensions.get("legacy"), current())  # noqa: SLF001 — cùng hệ thống
    store = ad.store() if ad is not None else None
    if store is None:
        abort(409, "Tổ chức này chưa có bộ tương thích agent v2 — chưa truyền tệp với máy trạm được")
    return store


def _send(kho: TenantFiles, meta: dict):
    p = kho.local_path(meta["key"])
    src: Any = p if p is not None else kho.open(meta["key"])
    return send_file(src, as_attachment=True, download_name=meta.get("name") or "file", max_age=0)


# ====================================================================== máy bạn ↔ máy trạm
@bp.post("/token")
@require_perm("device.control")
@bp.doc(summary="Cấp token truyền tệp (2 giờ) — máy trạm nộp tệp lên theo token này (lệnh `pull`)")
def token():
    return {"token": _store().new_fs_token(user=_uid())}


@bp.get("/pulled/<token>")
@require_perm("device.control")
@bp.doc(summary="Tải tệp máy trạm vừa nộp theo token (404 `pending` khi máy trạm chưa nộp xong)")
def pulled(token: str):
    store = _store()
    doc = store.fs_token(token)
    if doc is None or not (current().is_super or doc.get("user") == _uid()):
        abort(404, "Token sai, đã hết hạn hoặc không phải của bạn")
    meta = store.fs_file(doc, "pull_key")
    if meta is None:
        return {"status": "pending", "message": "Máy trạm chưa nộp xong"}, 404
    return _send(store.kho, meta)


@bp.post("/upload")
@require_perm("device.control")
@bp.doc(summary="Đưa một tệp của máy bạn lên Core (thân = luồng thô, `?name=`) → token để máy trạm tải (`push`)")
def upload():
    store = _store()
    name = safe_segment(request.args.get("name"))
    tok = store.new_fs_token(user=_uid())
    doc = store.kho.save("temp", ["fs", safe_segment(f"{tok}_{name}")], request.stream, name=name, by=_uid())
    store.fs_set(tok, "push_key", doc["key"])
    return {"token": tok, "filename": name, "size": doc["size"]}


@bp.get("/whoami")
@require_perm("device.control")
@bp.doc(summary="Ai đang mở trình quản lý tệp: có thấy khung Máy chủ không, máy đang ngồi (dò ngược IP, phải online)")
def whoami():
    ctx, ip = current(), str(g.client_ip or "")
    self_dev = None
    if ip:
        for d in devices.list_devices(current_app.extensions["itm_db"], ctx, current_app.extensions.get("legacy"),
                                      q=ip, online=True):
            if ip in (d.get("ip"), d.get("seen_ip")):
                self_dev = {"id": d["id"], "hostname": d.get("hostname"), "room_id": d.get("room_id")}
                break
    return {"super": ctx.is_super, "self_device": self_dev, "ip": ip}


# ====================================================================== khung "Máy chủ" (kho riêng của tổ chức)
def _drive() -> Drive:
    if not current().is_super:
        abort(403, "Chỉ Super Admin được dùng khung Máy chủ")
    return Drive(files_for(current_app, current().tenant_id))


class SrvIn(BaseModel):
    op: Literal["list", "mkdir", "delete", "recycle", "rename", "copy", "stage", "land"]
    path: str = Field(default="", max_length=900)
    name: str = Field(default="", max_length=255)
    target: str = Field(default="", max_length=900)
    src: str = Field(default="", max_length=900)
    dst: str = Field(default="", max_length=900)
    token: str = Field(default="", max_length=64)
    folder: str = Field(default="", max_length=900)
    filename: str = Field(default="", max_length=255)
    zipped: bool = False


@bp.post("/srv")
@require_perm("device.control")
@bp.input(SrvIn)
@bp.doc(summary="Khung Máy chủ: list / mkdir / delete / recycle (Thùng rác 30 ngày) / rename / copy / stage / land — "
                "cùng tên lệnh + dạng kết quả {ok, error} như máy trạm")
def srv(json_data: SrvIn):
    d, dr = json_data, _drive()
    res: dict = {"ok": False, "error": "", "op": d.op}
    try:
        if d.op == "list":
            res["path"], res["items"] = dr.list(d.path)
        elif d.op == "mkdir":
            res["name"] = dr.mkdir(d.path, d.name, by=_uid())
        elif d.op == "delete":
            dr.delete(d.target)
        elif d.op == "recycle":
            res["name"] = dr.recycle(d.target)
        elif d.op == "rename":
            dr.rename(d.src, d.dst)
        elif d.op == "copy":
            dr.copy(d.src, d.dst, by=_uid())
        elif d.op == "stage":
            store = _store()
            res.update(dr.stage(d.target, lambda: store.new_fs_token(user=_uid()),
                                lambda tok, key: store.fs_set(tok, "push_key", key), by=_uid()))
        elif d.op == "land":
            store = _store()
            doc = store.fs_token(d.token)
            pulled_meta = store.fs_file(doc, "pull_key")
            if doc is None or pulled_meta is None:
                raise LoiKho("Máy trạm chưa nộp xong (hoặc token đã hết hạn)")
            res["name"] = dr.land(pulled_meta, d.folder, d.filename, d.zipped, by=_uid())
        res["ok"] = True
    except LoiKho as e:
        res["error"] = str(e)
    return res


@bp.get("/srv/download")
@require_perm("device.control")
@bp.doc(summary="Khung Máy chủ: tải một tệp về máy bạn (`?path=`)")
def srv_download():
    dr = _drive()
    try:
        meta = dr.file(request.args.get("path", ""))
    except LoiKho as e:
        abort(404, str(e))
    return _send(dr.kho, meta)


@bp.post("/srv/upload")
@require_perm("device.control")
@bp.doc(summary="Khung Máy chủ: đưa một tệp của máy bạn vào thư mục `?path=` (thân = luồng thô, `?name=`)")
def srv_upload():
    dr = _drive()
    try:
        doc = dr.upload(request.args.get("path", ""), request.args.get("name"), request.stream, by=_uid())
    except LoiKho as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "name": doc["name"], "size": doc["size"]}
