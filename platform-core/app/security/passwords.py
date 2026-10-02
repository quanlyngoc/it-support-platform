"""Băm mật khẩu Argon2id (đặc tả V3, C13)."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()  # mặc định thư viện: Argon2id


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> tuple[bool, bool]:
    """Trả về (đúng mật khẩu?, cần băm lại?)."""
    if not stored_hash or not stored_hash.startswith("$argon2"):
        return False, False
    try:
        _ph.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False
    return True, _ph.check_needs_rehash(stored_hash)
