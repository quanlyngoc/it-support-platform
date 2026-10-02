"""API phòng + thiết bị (Sổ tay 5.1). Xem: đăng nhập là được (lọc theo phạm vi phòng của policy).
Chuyển phòng / xoá máy: quyền `device.manage` (hệ cũ §8.1: chỉ Super Admin & Administrator)."""
from __future__ import annotations

from datetime import datetime

from apiflask import APIBlueprint, abort
from flask import current_app, make_response
from pydantic import BaseModel, Field

from app.devices import service as svc
from app.rbac.perms import login_required, require_perm
from app.tenants.context import current

bp = APIBlueprint("devices", __name__, url_prefix="/api", tag="Phòng & thiết bị")


def _db():
    return current_app.extensions["itm_db"]


def _ad():
    return current_app.extensions.get("legacy")


# ====================================================================== phòng
@bp.get("/rooms")
@login_required
@bp.doc(summary="Danh sách phòng + số máy + số online (tuyệt đối)")
def rooms():
    items = svc.list_rooms(_db(), current(), _ad())
    return {"items": items, "total": len(items)}


@bp.get("/rooms/move-targets")
@require_perm("device.manage")
@bp.doc(summary="Phòng đích cho Chuyển phòng (có Phòng chờ)")
def move_targets():
    return {"items": svc.move_targets(_db(), current())}


@bp.get("/rooms/<room_id>")
@login_required
@bp.doc(summary="Chi tiết phòng + danh sách máy")
def room(room_id: str):
    r = svc.get_room(_db(), current(), _ad(), room_id)
    if r is None:
        abort(404, "Không có phòng này")
    return r


# ====================================================================== thiết bị
class DeviceQuery(BaseModel):
    room_id: str | None = None
    q: str | None = Field(default=None, max_length=64, description="Tìm theo tên máy / MAC / IP / serial")
    online: bool | None = None


@bp.get("/devices")
@login_required
@bp.input(DeviceQuery, location="query")
@bp.doc(summary="Danh sách máy (lọc theo phòng / từ khoá / online)")
def devices(query_data: DeviceQuery):
    items = svc.list_devices(_db(), current(), _ad(), room_id=query_data.room_id, q=query_data.q,
                             online=query_data.online)
    return {"items": items, "total": len(items)}


class EventQuery(BaseModel):
    q: str | None = Field(default=None, max_length=64)
    event: str | None = Field(default=None, max_length=32, description="trao_phan_cung | doi_serial | doi_mac")
    limit: int = Field(default=300, ge=1, le=2000)


@bp.get("/devices/events")
@require_perm("machine_events.view")
@bp.input(EventQuery, location="query")
@bp.doc(summary="Nhật ký thay đổi máy (tráo phần cứng / đổi serial / đổi MAC) + kho lưu trữ — chỉ đọc")
def events(query_data: EventQuery):
    return svc.machine_events(_db(), current(), q=query_data.q, event=query_data.event, limit=query_data.limit)


@bp.get("/reports/config-export")
@require_perm("device.manage")
@bp.doc(summary="Xuất cấu hình máy ra Excel 3 sheet (chỉ phòng chính thức) — như nút Xuất cấu hình của hệ cũ")
def config_export():
    from app.reports.config_export import build

    data, _n = build(svc.list_devices(_db(), current(), _ad(), limit=100_000))
    resp = make_response(data)
    resp.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=Cau_Hinh_Phong_May_{datetime.now():%Y%m%d_%H%M}.xlsx")
    return resp


@bp.get("/devices/<device_id>")
@login_required
@bp.doc(summary="Chi tiết một máy")
def device(device_id: str):
    d = svc.get_device(_db(), current(), _ad(), device_id)
    if d is None:
        abort(404, "Không có máy này")
    return d


class MoveIn(BaseModel):
    room_name: str = Field(min_length=1, max_length=100)
    seat: str = Field(default="", max_length=4, description="Số vị trí trong phòng (chỉ khi chuyển 1 máy)")


class MoveBulkIn(BaseModel):
    device_ids: list[str] = Field(min_length=1, max_length=500)
    room_name: str = Field(min_length=1, max_length=100)


def _move(ids: list[str], room_name: str, seat: str = ""):
    try:
        r = svc.move(_db(), current(), _ad(), ids, room_name, seat)
    except svc.LoiChuyen as e:
        abort(422, str(e))
    if not r["moved"]:
        abort(404, "Không có máy nào để chuyển", extra_data=r)
    return r


@bp.post("/devices/<device_id>/move")
@require_perm("device.manage")
@bp.input(MoveIn)
@bp.doc(summary="Chuyển 1 máy sang phòng khác (Move PC), tuỳ chọn số vị trí")
def move(device_id: str, json_data: MoveIn):
    return _move([device_id], json_data.room_name, json_data.seat)


@bp.post("/devices/move-bulk")
@require_perm("device.manage")
@bp.input(MoveBulkIn)
@bp.doc(summary="Chuyển nhiều máy sang một phòng")
def move_bulk(json_data: MoveBulkIn):
    return _move(json_data.device_ids, json_data.room_name)


@bp.delete("/devices/<device_id>")
@require_perm("device.manage")
@bp.doc(summary="Xoá máy khỏi danh sách (lưu trữ vào computers_archive trước)")
def delete(device_id: str):
    r = svc.delete(_db(), current(), _ad(), device_id)
    if r is None:
        abort(404, "Không có máy này")
    return r
