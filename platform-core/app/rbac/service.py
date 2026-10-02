"""Policy theo tổ chức: gói quyền (catalog) + phạm vi phòng."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.database import Database

from app.rbac.catalog import ids_for_codes, validate_permission_ids
from app.tenants.refs import require_refs
from app.tenants.repo import PolicyRepo


def create_policy(db: Database, tenant_id: ObjectId, name: str, *, permission_codes: Iterable[str] = (),
                  permission_ids: Iterable[ObjectId] = (), room_ids: Iterable[ObjectId] = (),
                  description: str = "") -> dict:
    perm_ids = validate_permission_ids(db, [*ids_for_codes(db, permission_codes), *permission_ids])
    rooms = list(dict.fromkeys(room_ids))
    require_refs(db, tenant_id, rooms=rooms)  # 4A.29: không gán phòng của tổ chức khác
    now = datetime.now(UTC)
    doc = {"name": name.strip(), "description": description, "system": False, "permission_ids": perm_ids,
           "room_ids": rooms, "created_at": now, "updated_at": now}
    doc["_id"] = PolicyRepo(db, tenant_id).insert_one(doc).inserted_id
    return doc
