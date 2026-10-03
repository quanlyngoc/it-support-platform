"""Sự cố (collection `incidents`) — phần CHỈ ĐỌC cho Dashboard Desktop (Sổ tay 4.6). Quy trình xử lý phiếu (nhận,
ghi chú, hoàn thành) làm ở GĐ8.

Sự cố lưu `room_name` (tên phòng lúc tạo — như hệ cũ), không phải `room_id`. Người bị giới hạn phòng chỉ thấy sự cố của
các phòng mình: đổi `ctx.room_ids` → tên phòng rồi lọc theo `room_name`.
"""
from __future__ import annotations

from datetime import datetime
from re import escape
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.tenants.context import Ctx
from app.tenants.repo import repo_for

DANG_MO = ("PENDING", "PROCESSING")
PHAN_CUNG = ("hardware_ram", "hardware_disk", "cmos")  # do bộ ghi tự phát hiện (hardware.py)
_TEXT = ("hostname", "room_name", "title", "description", "category", "status", "source", "reporter_name")


def _scope(db: Database, ctx: Ctx) -> dict:
    if ctx.is_super or not ctx.room_ids:
        return {}
    names = [r["name"] for r in repo_for(db, ctx.tenant_id, "rooms").find({"_id": {"$in": list(ctx.room_ids)}},
                                                                          {"name": 1})]
    return {"room_name": {"$in": names}}


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
    return out


def list_incidents(db: Database, ctx: Ctx, *, status: str | None = None, q: str | None = None,
                   hostname: str | None = None, room_id: str | None = None, limit: int = 200) -> list[dict]:
    query: dict = dict(_scope(db, ctx))
    if room_id:
        try:
            rid = ObjectId(room_id)
        except Exception:
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
    if q:
        rx = {"$regex": escape(q.strip()), "$options": "i"}
        query["$or"] = [{"hostname": rx}, {"title": rx}, {"room_name": rx}]
    cur = repo_for(db, ctx.tenant_id, "incidents").find(query, {"tenant_id": 0}).sort("created_at", -1).limit(limit)
    return [public(d) for d in cur]


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
