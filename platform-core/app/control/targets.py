"""Chọn máy đích cho một lệnh: theo danh sách máy HOẶC cả phòng — luôn lọc theo phạm vi phòng của policy + tổ chức.

Máy ngoài phạm vi / không tồn tại → vào danh sách bỏ qua kèm lý do (không lộ máy của phòng / tổ chức khác).
Cả phòng: mặc định CHỪA máy giảng viên (như `power_control` hệ cũ — bật/tắt cả phòng không đụng máy GV).
"""
from __future__ import annotations

from typing import Any

from pymongo.database import Database

from app.devices import service as devices
from app.legacy_adapter.identity import is_teacher_pc
from app.tenants.context import Ctx


class LoiDich(ValueError):
    pass


def resolve(db: Database, ctx: Ctx, ad: Any, *, device_ids: list[str] | None = None, room_id: str | None = None,
            exclude_gv: bool = True) -> tuple[list[dict], list[dict]]:
    """→ (máy đích, bỏ qua[{id|hostname, reason}]). Đúng MỘT trong device_ids / room_id."""
    if bool(device_ids) == bool(room_id):
        raise LoiDich("Cần đúng một trong hai: danh sách máy hoặc phòng")
    skipped: list[dict] = []
    if room_id:
        if devices.get_room(db, ctx, ad, room_id) is None:
            raise LoiDich("Không có phòng này")
        found = devices.list_devices(db, ctx, ad, room_id=room_id)
        if exclude_gv:
            skipped += [{"hostname": d["hostname"], "reason": "máy giảng viên"} for d in found
                        if is_teacher_pc(d.get("hostname"))]
            found = [d for d in found if not is_teacher_pc(d.get("hostname"))]
        return found, skipped
    out: list[dict] = []
    seen: set[str] = set()
    for did in device_ids or []:
        if did in seen:
            continue
        seen.add(did)
        d = devices.get_device(db, ctx, ad, did)
        if d is None:
            skipped.append({"id": did, "reason": "không có máy này"})
        else:
            out.append(d)
    return out, skipped
