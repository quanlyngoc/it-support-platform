"""Kiểm quan hệ trước khi ghi (đặc tả 4A.29): mọi tham chiếu phải cùng tổ chức, không có tham chiếu chéo.

    require_refs(db, ctx.tenant_id, rooms=room_id, computers=[id1, id2])

Không tìm thấy trong tổ chức hiện tại (kể cả vì thuộc tổ chức khác) -> RefNotFound; route đổi thành 404,
KHÔNG tiết lộ tài nguyên có tồn tại ở tổ chức khác hay không.
"""
from __future__ import annotations

from collections.abc import Iterable

from bson import ObjectId
from pymongo.database import Database

from app.tenants.repo import TenantScopeError, repo_for


class RefNotFound(TenantScopeError):
    def __init__(self, collection: str, missing: list[ObjectId]):
        super().__init__(f"Không tìm thấy {collection}: {', '.join(map(str, missing))}")
        self.collection = collection
        self.missing = missing


def _ids(v: ObjectId | Iterable[ObjectId] | None) -> list[ObjectId]:
    if v is None:
        return []
    if isinstance(v, ObjectId):
        return [v]
    return list(dict.fromkeys(v))


def require_refs(db: Database, tenant_id: ObjectId, **refs: ObjectId | Iterable[ObjectId] | None) -> None:
    for collection, value in refs.items():
        ids = _ids(value)
        if not ids:
            continue
        if not all(isinstance(i, ObjectId) for i in ids):
            raise RefNotFound(collection, [i for i in ids if not isinstance(i, ObjectId)])
        found = {d["_id"] for d in repo_for(db, tenant_id, collection).find({"_id": {"$in": ids}}, {"_id": 1})}
        missing = [i for i in ids if i not in found]
        if missing:
            raise RefNotFound(collection, missing)
