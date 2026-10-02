"""Phòng máy (collection `rooms`, đặc tả 4A). Mỗi tên phòng có một tài liệu → `_id` cố định cho
`computers.room_id`, URL `/api/rooms/<id>` và room realtime `t:<tenant>:room:<id>`. Tên phòng vẫn suy từ tên máy /
chuyển phòng tay như hệ cũ.
"""
from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId
from pymongo.database import Database

from app.legacy_adapter.identity import is_official_room
from app.tenants.repo import repo_for

PHONG_CHO = "Phòng chờ"


def ensure_room(db: Database, tenant_id: ObjectId, name: str) -> ObjectId:
    """Lấy `_id` của phòng theo tên, tạo nếu chưa có (an toàn khi gọi đồng thời nhờ unique (tenant_id, name))."""
    repo = repo_for(db, tenant_id, "rooms")
    now = datetime.now(UTC)
    repo.update_one({"name": name}, {"$setOnInsert": {"official": is_official_room(name), "created_at": now}},
                    upsert=True)
    doc = repo.find_one({"name": name}, {"_id": 1})
    assert doc is not None
    return doc["_id"]


def room_ids(db: Database, tenant_id: ObjectId) -> dict[str, ObjectId]:
    return {d["name"]: d["_id"] for d in repo_for(db, tenant_id, "rooms").find({}, {"name": 1})}


def sort_key(name: str) -> tuple[int, str]:
    """Phòng chính thức trước, rồi theo tên (giống /api/move_targets cũ)."""
    return (0 if is_official_room(name) else 1, name)
