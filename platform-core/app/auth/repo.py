"""Repo phiên đăng nhập."""
from __future__ import annotations

from pymongo.database import Database

from app.tenants.repo import TenantRepo


class SessionRepo(TenantRepo):
    collection = "sessions"


class ActiveSessionRepo(TenantRepo):
    collection = "active_sessions"


def find_session_by_token_hash(db: Database, token_hash: str) -> dict | None:
    """Ngoại lệ DUY NHẤT tra cứu không theo tổ chức: bước khởi đầu để BIẾT tổ chức của request.

    An toàn vì khoá tra cứu là SHA-256 của token ngẫu nhiên 256-bit (unique index), và tenant_id trả về
    chính là nguồn sự thật để dựng ngữ cảnh (Ctx) — client không thể chọn tổ chức.
    """
    return db["sessions"].find_one({"session_token_hash": token_hash, "is_active": True})
