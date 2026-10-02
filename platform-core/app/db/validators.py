"""Validator $jsonSchema (mức moderate) — chốt chặn thứ hai sau TenantRepo: thiếu tenant_id là CSDL từ chối."""
from __future__ import annotations

from pymongo.database import Database

from app.db.collections import PLATFORM_OWNED, TENANT_OWNED

_OID = {"bsonType": "objectId"}


def _schema(required: list[str], props: dict) -> dict:
    return {"$jsonSchema": {"bsonType": "object", "required": required, "properties": props}}


def build() -> dict[str, dict]:
    v: dict[str, dict] = {}
    for col in TENANT_OWNED:
        v[col] = _schema(["tenant_id"], {"tenant_id": _OID})
    v["users"] = _schema(["tenant_id", "username", "username_lc", "user_type"], {
        "tenant_id": _OID, "username": {"bsonType": "string"}, "username_lc": {"bsonType": "string"},
        "user_type": {"enum": ["LOCAL", "AD"]}, "policy_ids": {"bsonType": "array"}})
    v["computers"] = _schema(["tenant_id", "hostname"], {"tenant_id": _OID, "hostname": {"bsonType": "string"}})
    v["sessions"] = _schema(["tenant_id", "user_id", "session_token_hash", "expires_at"], {
        "tenant_id": _OID, "user_id": _OID, "session_token_hash": {"bsonType": "string"},
        "expires_at": {"bsonType": "date"}})
    v["incidents"] = _schema(["tenant_id", "status"], {"tenant_id": _OID,
                                                       "status": {"enum": ["PENDING", "PROCESSING", "DONE"]}})
    v["tenants"] = _schema(["code", "name", "status"], {
        "code": {"bsonType": "string"}, "name": {"bsonType": "string"},
        "status": {"enum": ["ACTIVE", "SUSPENDED", "DISABLED"]}})
    v["permissions"] = _schema(["code"], {"code": {"bsonType": "string"}})
    assert set(v) == set(TENANT_OWNED) | set(PLATFORM_OWNED)
    return v


def apply(db: Database) -> int:
    """Tạo collection kèm validator, hoặc cập nhật validator nếu đã có. Trả về số collection đã xử lý."""
    existing = set(db.list_collection_names())
    rules = build()
    for col, validator in rules.items():
        if col in existing:
            db.command("collMod", col, validator=validator, validationLevel="moderate")
        else:
            db.create_collection(col, validator=validator, validationLevel="moderate")
    return len(rules)
