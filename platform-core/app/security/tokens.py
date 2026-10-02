"""Token phiên: trả token ngẫu nhiên cho client, CSDL chỉ lưu SHA-256 của token."""
from __future__ import annotations

import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
