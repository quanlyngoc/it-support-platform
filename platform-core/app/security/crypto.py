"""Mã hoá secret cấu hình (SMTP, LDAP bind, Telegram, Gemini, TOTP) bằng AES-256-GCM."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "v1:"


def _key(master_key_b64: str) -> bytes:
    # Chuẩn hoá mọi khoá đầu vào về 32 byte
    return hashlib.sha256(base64.b64decode(master_key_b64)).digest()


def encrypt(plaintext: str, master_key_b64: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key(master_key_b64)).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str, master_key_b64: str) -> str:
    if not token.startswith(_PREFIX):
        raise ValueError("Dữ liệu mã hoá không đúng định dạng")
    raw = base64.b64decode(token[len(_PREFIX):])
    return AESGCM(_key(master_key_b64)).decrypt(raw[:12], raw[12:], None).decode("utf-8")
