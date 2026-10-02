"""Index theo bảng 4A.30 của đặc tả (bản V3: mac/hostname KHÔNG unique; định danh máy = agent_id)."""
from __future__ import annotations

from pymongo import ASCENDING as A
from pymongo import DESCENDING as Z
from pymongo.database import Database

_STR = {"$type": "string"}

INDEXES: dict[str, list[tuple[list, dict]]] = {
    "tenants": [([("code", A)], {"unique": True}), ([("status", A)], {})],
    "permissions": [([("code", A)], {"unique": True})],
    "users": [([("tenant_id", A), ("username_lc", A)], {"unique": True}), ([("tenant_id", A), ("email", A)], {})],
    "ad_user_policies": [([("tenant_id", A), ("username_lc", A)], {"unique": True}),
                         ([("tenant_id", A), ("upn", A)], {"unique": True, "partialFilterExpression": {"upn": _STR}})],
    "policies": [([("tenant_id", A), ("name", A)], {"unique": True})],
    "rooms": [([("tenant_id", A), ("name", A)], {"unique": True})],
    "computers": [
        ([("tenant_id", A), ("agent_id", A)], {"unique": True, "partialFilterExpression": {"agent_id": _STR}}),
        ([("tenant_id", A), ("legacy_hostname", A)], {"unique": True,
                                                       "partialFilterExpression": {"legacy_hostname": _STR}}),
        ([("tenant_id", A), ("mac", A)], {}),
        ([("tenant_id", A), ("hostname", A)], {}),
        ([("tenant_id", A), ("room_id", A)], {}),
        ([("tenant_id", A), ("is_online", A)], {}),
        ([("tenant_id", A), ("last_heartbeat_at", Z)], {}),
    ],
    "agents": [([("tenant_id", A), ("agent_id", A)], {"unique": True}),
               ([("tenant_id", A), ("device_id", A)], {"unique": True}),
               ([("tenant_id", A), ("status", A)], {})],
    "agent_enrollments": [([("code_hash", A)], {"unique": True}), ([("tenant_id", A), ("status", A)], {}),
                          ([("expires_at", A)], {"expireAfterSeconds": 0})],
    "incidents": [([("tenant_id", A), ("status", A), ("created_at", Z)], {}),
                  ([("tenant_id", A), ("room_id", A), ("created_at", Z)], {}),
                  ([("tenant_id", A), ("device_id", A), ("created_at", Z)], {}),
                  ([("tenant_id", A), ("hostname", A), ("created_at", Z)], {}),
                  ([("tenant_id", A), ("source", A), ("created_at", Z)], {})],
    "usage_stats": [([("tenant_id", A), ("device_id", A), ("date", A)], {"unique": True})],
    "online_state": [([("tenant_id", A), ("device_id", A)], {"unique": True})],
    "client_logs": [([("tenant_id", A), ("device_id", A), ("created_at", Z)], {}),
                    ([("created_at", A)], {"expireAfterSeconds": 90 * 86400})],
    "sessions": [([("session_token_hash", A)], {"unique": True}), ([("tenant_id", A), ("user_id", A)], {}),
                 ([("expires_at", A)], {"expireAfterSeconds": 0})],
    "active_sessions": [([("tenant_id", A), ("user_id", A)], {"unique": True})],
    "settings": [([("tenant_id", A), ("key", A)], {"unique": True})],
    "chat_messages": [([("tenant_id", A), ("scope", A), ("room_id", A), ("created_at", Z)], {})],
    "chat_reads": [([("tenant_id", A), ("user_id", A), ("room_id", A), ("scope", A)], {"unique": True})],
    "chat_reactions": [([("tenant_id", A), ("message_id", A), ("user_id", A), ("reaction", A)], {"unique": True})],
    "audit_log": [([("tenant_id", A), ("created_at", Z)], {}),
                  ([("tenant_id", A), ("system", A), ("created_at", Z)], {}),
                  ([("created_at", A)], {"expireAfterSeconds": 180 * 86400})],
    "pushed_files": [([("tenant_id", A), ("batch_id", A)], {}), ([("tenant_id", A), ("device_id", A)], {})],
    "file_metadata": [([("tenant_id", A), ("scope", A), ("created_at", Z)], {}),
                      ([("expires_at", A)], {"expireAfterSeconds": 0, "partialFilterExpression":
                                             {"expires_at": {"$type": "date"}}})],
    "machine_events": [([("tenant_id", A), ("created_at", Z)], {}), ([("tenant_id", A), ("hostname", A)], {})],
    "computers_archive": [([("tenant_id", A), ("archived_at", Z)], {})],
    "command_results": [([("tenant_id", A), ("token", A)], {}),
                        ([("created_at", A)], {"expireAfterSeconds": 2 * 86400})],
}


def ensure(db: Database) -> int:
    """Tạo mọi index (an toàn khi chạy lại). Trả về số index đã khai báo."""
    n = 0
    for col, specs in INDEXES.items():
        for keys, opts in specs:
            db[col].create_index(keys, **opts)
            n += 1
    return n
