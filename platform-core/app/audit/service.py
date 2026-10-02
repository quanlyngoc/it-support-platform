"""Ghi nhật ký hệ thống (mang từ hệ cũ §8.5): mọi thao tác thay đổi, tách theo hệ LAB/HSK/THI."""
from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId
from pymongo.database import Database

from app.tenants.repo import AuditRepo


def write_audit(db: Database, tenant_id: ObjectId, *, action: str, actor: str = "", actor_user_id=None,
                detail: str = "", ip: str = "", system: str = "LAB", status: int | None = None) -> None:
    try:
        AuditRepo(db, tenant_id).insert_one({
            "action": action, "actor": actor, "actor_user_id": actor_user_id, "detail": detail[:2000],
            "ip": ip, "system": system, "status": status, "created_at": datetime.now(UTC)})
    except Exception:
        pass  # nhật ký lỗi không được làm hỏng nghiệp vụ chính
