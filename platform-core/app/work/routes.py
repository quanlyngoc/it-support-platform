"""API giao bài / thu bài (Sổ tay 7.3). Quyền `device.control` (hệ cũ: đăng nhập là giao/thu được) + phạm vi phòng.

Đối chiếu hệ cũ: `/upload_work` → `POST /api/work/upload` (từng tệp, luồng thô, giữ đường dẫn con) · `/send_work` +
`/hub_send_work` → `POST /api/work/send` · `/send_status/<sid>` → `GET /api/work/send/<sid>` · `/hub_pushed_list` →
`GET /api/work/pushed` · `/hub_delete_pushed` → `POST /api/work/pushed/delete` · `/collect_work` + `/hub_collect_work` →
`POST /api/work/collect` · `/collect_status` + `/hub_collect_status` → `GET /api/work/collect/<sid>` ·
`/collect_download/<sid>/<host>` → `…/hosts/<host>/zip` · `/collect_download_all/<sid>` → `…/zip`.
"""
from __future__ import annotations

from typing import Any, Literal

from apiflask import APIBlueprint, abort
from flask import Response, current_app, request, send_file
from pydantic import BaseModel, Field

from app.control.targets import LoiDich
from app.devices import service as devices
from app.rbac.perms import require_perm
from app.storage import safe_segment
from app.tenants.context import current
from app.work import service as svc

bp = APIBlueprint("work", __name__, url_prefix="/api/work", tag="Giao bài / thu bài")


def _db():
    return current_app.extensions["itm_db"]


def _live() -> Any:
    ad = devices._live(current_app.extensions.get("legacy"), current())  # noqa: SLF001 — cùng hệ thống
    if ad is None or ad.store() is None:
        abort(409, "Tổ chức này chưa có bộ tương thích agent v2 — chưa giao/thu bài được")
    return ad


def _limited() -> bool:
    ctx = current()
    return bool(ctx.room_ids) and not ctx.is_super


def _mine(st: dict | None) -> dict:
    """Người bị giới hạn phòng chỉ xem phiên CỦA MÌNH (như PowerShell hàng loạt)."""
    if st is None or (_limited() and st["_by_user_id"] != str(current().user_id)):
        abort(404, "Không có phiên này")
    return {k: v for k, v in st.items() if not k.startswith("_")}


def _loi(e: LoiDich):
    abort(404 if "không tồn tại" in str(e) or "Không có" in str(e) else 422, str(e))


class TargetsIn(BaseModel):
    room_ids: list[str] = Field(default_factory=list, max_length=200)
    device_ids: list[str] = Field(default_factory=list, max_length=2000)
    mode: Literal["students", "teachers", "all"] = Field(default="students",
                                                         description="Theo phòng: máy SV · máy GV · tất cả")


# ====================================================================== GIAO BÀI
@bp.post("/upload")
@require_perm("device.control")
@bp.doc(summary="Thêm 1 tệp vào lô giao bài (thân = luồng thô; `?name=` giữ đường dẫn con khi chọn cả thư mục; "
                "`?batch=` để thêm vào lô đang có)")
def upload():
    ctx = current()
    try:
        return svc.upload(_live().store().kho, uid=str(ctx.user_id), may_all=ctx.is_super,
                          batch=request.args.get("batch"), name=request.args.get("name"), stream=request.stream)
    except LoiDich as e:
        _loi(e)
    except PermissionError as e:
        abort(403, str(e))


@bp.get("/batches/<batch_id>")
@require_perm("device.control")
@bp.doc(summary="Các tệp trong một lô giao bài")
def batch(batch_id: str):
    files = svc.batch_files(_live().store().kho, svc.hexid(batch_id))
    if not files:
        abort(404, "Lô tệp không tồn tại hoặc đã quá 48 giờ")
    return {"batch_id": svc.hexid(batch_id), "files": [{"name": f["name"], "size": f["size"]} for f in files]}


class SendIn(TargetsIn):
    batch_id: str = Field(min_length=8, max_length=64)
    dest_folder: str = Field(default="", max_length=260,
                             description="Rỗng = Desktop chung (C:\\Users\\Public\\Desktop)")
    overwrite: bool = Field(default=False, description="Ghi đè tệp trùng tên (không tích = giữ tệp cũ, bỏ qua)")


@bp.post("/send")
@require_perm("device.control")
@bp.input(SendIn)
@bp.doc(summary="Giao lô tệp tới các phòng (máy SV / GV / tất cả) hoặc các máy đã chọn — kết quả theo session_id")
def send(json_data: SendIn):
    ad = _live()
    try:
        return svc.send(_db(), current(), ad, batch_id=json_data.batch_id, room_ids=json_data.room_ids,
                        device_ids=json_data.device_ids, mode=json_data.mode, dest=json_data.dest_folder.strip(),
                        overwrite=json_data.overwrite)
    except LoiDich as e:
        _loi(e)


@bp.get("/send/<sid>")
@require_perm("device.control")
@bp.doc(summary="Kết quả nhận bài từng máy (máy quá hạn chưa báo → timeout)")
def send_status(sid: str):
    return _mine(svc.send_status(_live(), sid))


@bp.get("/pushed")
@require_perm("device.control")
@bp.doc(summary="Nhật ký tệp đã giao (đã đẩy / chờ xoá / đã xoá) theo từng máy")
def pushed():
    return {"items": svc.pushed_list(_db(), current(), _live())}


class DelIn(BaseModel):
    room_ids: list[str] = Field(default_factory=list, max_length=200, description="Rỗng = mọi phòng trong phạm vi")


@bp.post("/pushed/delete")
@require_perm("device.control")
@bp.input(DelIn)
@bp.doc(summary="XOÁ VĨNH VIỄN các tệp đã giao (chỉ tệp agent báo đã ghi); máy đang tắt → tự xoá khi online lại")
def pushed_delete(json_data: DelIn):
    return svc.delete_pushed(_db(), current(), _live(), json_data.room_ids or None)


# ====================================================================== THU BÀI
class CollectIn(TargetsIn):
    src_folder: str = Field(min_length=3, max_length=260)
    patterns: list[str] = Field(default_factory=lambda: ["*"], max_length=20,
                                description="Mẫu tên tệp: * = tất cả; *.docx, *.pdf…")
    delete_after: bool = Field(default=False, description="Xoá VĨNH VIỄN tệp gốc sau khi nộp thành công")
    save_thu: bool = Field(default=False, description="Lưu bản giải nén trên máy chủ: thu/<Ca>/<Phòng>/<Máy>/")
    ca: str = Field(default="", max_length=20, description="Ca sáng / Ca chiều (rỗng = theo giờ máy chủ)")


@bp.post("/collect")
@require_perm("device.control")
@bp.input(CollectIn)
@bp.doc(summary="Thu bài từ các phòng / các máy đã chọn — kết quả theo session_id")
def collect(json_data: CollectIn):
    if json_data.save_thu and _limited():
        abort(403, "Lưu bài thu trên máy chủ (cấu trúc THU) chỉ dành cho tài khoản quản trị toàn trường")
    ad = _live()
    try:
        return svc.collect(_db(), current(), ad, room_ids=json_data.room_ids, device_ids=json_data.device_ids,
                           mode=json_data.mode, src=json_data.src_folder.strip(), patterns=json_data.patterns,
                           delete_after=json_data.delete_after, save_thu=json_data.save_thu, ca=json_data.ca)
    except LoiDich as e:
        _loi(e)


@bp.get("/collect/<sid>")
@require_perm("device.control")
@bp.doc(summary="Trạng thái thu bài từng máy: ok / nofile / nofolder / fail / offline / running")
def collect_status(sid: str):
    return _mine(svc.collect_status(_live(), sid))


def _st(sid: str) -> tuple[Any, dict]:
    ad = _live()
    return ad, _mine(svc.collect_status(ad, sid))


@bp.get("/collect/<sid>/zip")
@require_perm("device.control")
@bp.doc(summary="Tải MỌI bài đã nộp trong một tệp .zip (<Phòng>/<Máy>.zip)")
def collect_zip_all(sid: str):
    ad, st = _st(sid)
    tmp = svc.zip_all(ad.store(), st)
    if tmp is None:
        abort(404, "Chưa máy nào nộp bài")
    resp = send_file(tmp, as_attachment=True, mimetype="application/zip", max_age=0,
                     download_name=f"BaiThu_{safe_segment(st.get('ca') or '')}_{sid[:8]}.zip")
    resp.call_on_close(tmp.close)
    return resp


@bp.get("/collect/<sid>/hosts/<host>/zip")
@require_perm("device.control")
@bp.doc(summary="Tải bài (.zip) của một máy")
def collect_zip_one(sid: str, host: str):
    ad, _ = _st(sid)
    doc = svc.zip_doc(ad.store(), sid, host)
    if doc is None:
        abort(404, "Máy này chưa nộp bài")
    p = ad.store().kho.local_path(doc["key"])
    src: Any = p if p is not None else ad.store().kho.open(doc["key"])
    return send_file(src, as_attachment=True, mimetype="application/zip", max_age=0,
                     download_name=safe_segment(f"{host}.zip"))


@bp.get("/collect/<sid>/hosts/<host>/entries")
@require_perm("device.control")
@bp.doc(summary="Các tệp trong bài của một máy (để lưu thẳng vào <thư mục>/<phòng>/<máy>/ trên máy bạn)")
def collect_entries(sid: str, host: str):
    ad, _ = _st(sid)
    items = svc.entries(ad.store(), sid, host)
    if items is None:
        abort(404, "Máy này chưa nộp bài")
    return {"items": items}


@bp.get("/collect/<sid>/hosts/<host>/entry")
@require_perm("device.control")
@bp.doc(summary="Tải MỘT tệp trong bài của một máy (`?path=` như trong entries) — theo luồng")
def collect_entry(sid: str, host: str):
    ad, _ = _st(sid)
    r = svc.entry_stream(ad.store(), sid, host, request.args.get("path", ""))
    if r is None:
        abort(404, "Không có tệp này trong bài")
    name, size, gen = r
    resp = Response(gen, mimetype="application/octet-stream")
    resp.headers["Content-Length"] = str(size)
    resp.headers["Content-Disposition"] = "attachment"
    resp.headers["X-File-Name"] = safe_segment(name).encode("utf-8").hex()  # tên tiếng Việt an toàn qua header
    return resp
