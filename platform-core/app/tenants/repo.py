"""TenantRepo — lối DUY NHẤT để truy cập collection tenant-owned (quy tắc AI 1–5, đặc tả 4A.3, 4A.35).

Mọi truy vấn tự gắn tenant_id; truy vấn/ghi mang tenant_id KHÁC bị từ chối bằng TenantScopeError.
"""
from __future__ import annotations

from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.db.collections import TENANT_OWNED


class TenantScopeError(Exception):
    """Vi phạm ranh giới tổ chức."""


def _changes_tenant(update: dict, tid: ObjectId) -> bool:
    """True nếu bản cập nhật cố đặt/đổi tenant_id (chỉ cho phép $setOnInsert đúng tổ chức hiện tại)."""
    for op, body in update.items():
        if op == "tenant_id":
            return True
        if isinstance(body, dict) and "tenant_id" in body:
            if not (op == "$setOnInsert" and body["tenant_id"] == tid):
                return True
    return False


class TenantRepo:
    collection: str = ""

    def __init__(self, db: Database, tenant_id: ObjectId):
        if not isinstance(tenant_id, ObjectId):
            raise TenantScopeError("tenant_id phải là ObjectId lấy từ phiên")
        if self.collection not in TENANT_OWNED:
            raise TenantScopeError(f"{self.collection!r} không phải collection tenant-owned")
        self.db = db
        self.col = db[self.collection]
        self.tid = tenant_id

    @classmethod
    def for_ctx(cls, db: Database, ctx) -> TenantRepo:
        return cls(db, ctx.tenant_id)

    # ---------- dựng truy vấn ----------
    def _q(self, q: dict | None = None) -> dict:
        q = dict(q or {})
        if "tenant_id" in q and q["tenant_id"] != self.tid:
            raise TenantScopeError("Truy vấn chéo tổ chức")
        q["tenant_id"] = self.tid
        return q

    def _doc(self, doc: dict) -> dict:
        if "tenant_id" in doc and doc["tenant_id"] != self.tid:
            raise TenantScopeError("Ghi dữ liệu sang tổ chức khác")
        return {**doc, "tenant_id": self.tid}

    def _upd(self, update: dict) -> dict:
        if _changes_tenant(update, self.tid):
            raise TenantScopeError("Không được đổi tenant_id")
        return update

    # ---------- đọc ----------
    def find(self, q: dict | None = None, *args: Any, **kw: Any):
        return self.col.find(self._q(q), *args, **kw)

    def find_one(self, q: dict | None = None, *args: Any, **kw: Any):
        return self.col.find_one(self._q(q), *args, **kw)

    def get(self, _id: ObjectId, *args: Any, **kw: Any):
        return self.col.find_one(self._q({"_id": _id}), *args, **kw)

    def count(self, q: dict | None = None) -> int:
        return self.col.count_documents(self._q(q))

    def aggregate(self, pipeline: list[dict], **kw: Any):
        for stage in pipeline:
            if "$lookup" in stage or "$unionWith" in stage or "$out" in stage or "$merge" in stage:
                raise TenantScopeError("Stage chéo collection phải đi qua service có kiểm tổ chức")
        return self.col.aggregate([{"$match": {"tenant_id": self.tid}}, *pipeline], **kw)

    # ---------- ghi ----------
    def insert_one(self, doc: dict):
        return self.col.insert_one(self._doc(doc))

    def insert_many(self, docs: list[dict]):
        return self.col.insert_many([self._doc(d) for d in docs])

    def update_one(self, q: dict, update: dict, upsert: bool = False):
        return self.col.update_one(self._q(q), self._upd(update), upsert=upsert)

    def update_many(self, q: dict, update: dict):
        return self.col.update_many(self._q(q), self._upd(update))

    def update_by_id(self, _id: ObjectId, update: dict):
        return self.col.update_one(self._q({"_id": _id}), self._upd(update))

    def delete_one(self, q: dict):
        return self.col.delete_one(self._q(q))

    def delete_by_id(self, _id: ObjectId):
        return self.col.delete_one(self._q({"_id": _id}))

    def delete_many(self, q: dict):
        if not q:
            raise TenantScopeError("delete_many cần điều kiện cụ thể")
        return self.col.delete_many(self._q(q))


# ---- Repo dùng chung ----
class UserRepo(TenantRepo):
    collection = "users"


class AdUserRepo(TenantRepo):
    collection = "ad_user_policies"


class PolicyRepo(TenantRepo):
    collection = "policies"


class SettingRepo(TenantRepo):
    collection = "settings"


class AuditRepo(TenantRepo):
    collection = "audit_log"


class ComputerRepo(TenantRepo):
    collection = "computers"


class RoomRepo(TenantRepo):
    collection = "rooms"


_REPO_CACHE: dict[str, type[TenantRepo]] = {}


def repo_for(db: Database, tenant_id: ObjectId, collection: str) -> TenantRepo:
    """Repo cho một collection tenant-owned bất kỳ (dùng cho kiểm tham chiếu, báo cáo, test)."""
    cls = _REPO_CACHE.get(collection)
    if cls is None:
        if collection not in TENANT_OWNED:
            raise TenantScopeError(f"{collection!r} không phải collection tenant-owned")
        cls = type(f"{collection.title().replace('_', '')}Repo", (TenantRepo,), {"collection": collection})
        _REPO_CACHE[collection] = cls
    return cls(db, tenant_id)
