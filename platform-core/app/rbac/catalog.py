"""Catalog quyền (platform-owned): kiểm policy chỉ tham chiếu quyền có thật (đặc tả 4A.36 mục 13)."""
from __future__ import annotations

from collections.abc import Iterable

from bson import ObjectId
from pymongo.database import Database


class UnknownPermission(ValueError):
    def __init__(self, missing: list):
        super().__init__(f"Quyền không tồn tại trong catalog: {', '.join(map(str, missing))}")
        self.missing = missing


def validate_permission_ids(db: Database, ids: Iterable[ObjectId]) -> list[ObjectId]:
    ids = list(dict.fromkeys(ids))
    found = {d["_id"] for d in db.permissions.find({"_id": {"$in": ids}}, {"_id": 1})}
    missing = [i for i in ids if i not in found]
    if missing:
        raise UnknownPermission(missing)
    return ids


def ids_for_codes(db: Database, codes: Iterable[str]) -> list[ObjectId]:
    codes = list(dict.fromkeys(codes))
    rows = {d["code"]: d["_id"] for d in db.permissions.find({"code": {"$in": codes}}, {"code": 1})}
    missing = [c for c in codes if c not in rows]
    if missing:
        raise UnknownPermission(missing)
    return [rows[c] for c in codes]
