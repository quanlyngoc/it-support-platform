"""Đăng nhập / đăng xuất từ xa (Sổ tay 6.2) — thay `/remote_login` + `/remote_logout` của hub cũ.

Đăng nhập: `{"command_obj": {"action": "login_encrypted", "data": hex(nonce 12 B + AES-GCM(ciphertext))}}` với bản rõ
`{"user", "pass"}` — ĐÚNG định dạng agent 2.7.5.3 giải (client.py: nonce = 24 ký tự hex đầu). Khoá AES-256 dùng chung
với agent (Registry `HKLM\\SOFTWARE\\PhenikaaIT\\AesKey`), Core đọc từ `.env` (`AES_256_KEY_HEX`).
Agent kiểm mật khẩu tại máy rồi báo `/login_result/<mac>` → Core gửi `login_response` về ĐÚNG người bấm (room
`t:<tenant>:u:<user>`). Mật khẩu KHÔNG ghi log / nhật ký (nhật ký audit chỉ ghi đường dẫn + người bấm).
Đăng xuất: `{"command": "logout"}` (đúng dạng hub cũ).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.legacy_adapter.identity import norm_host


class ThieuKhoa(RuntimeError):
    pass


def encrypt(key_hex: str, user: str, password: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key_hex or ""):
        raise ThieuKhoa("Chưa cấu hình khoá AES (AES_256_KEY_HEX, 64 ký tự hex) — không đăng nhập từ xa được")
    nonce = os.urandom(12)
    ct = AESGCM(bytes.fromhex(key_hex)).encrypt(nonce, json.dumps({"user": user, "pass": password}).encode("utf-8"),
                                                None)
    return nonce.hex() + ct.hex()


def _send(ad: Any, targets: list[dict], payload_of, on_sent=None) -> dict:
    sent, skipped = [], []
    for d in targets:
        if not d.get("is_online"):
            skipped.append({"hostname": d["hostname"], "reason": "máy đang tắt"})
            continue
        r = ad.dispatch(norm_host(d["hostname"]), d.get("mac") or "", payload_of(d))
        if r["channel"] == "none":
            skipped.append({"hostname": d["hostname"], "reason": "mất kênh lệnh"})
            continue
        if on_sent:
            on_sent(d)
        sent.append({"hostname": d["hostname"], "channel": r["channel"]})
    return {"sent": sent, "skipped": skipped}


def login(ad: Any, targets: list[dict], key_hex: str, user: str, password: str, reply_room: str) -> dict:
    data = encrypt(key_hex, user, password)  # mỗi lệnh dùng chung 1 bản mã (như hub cũ) — nonce mới mỗi lần bấm
    return _send(ad, targets, lambda d: {"command_obj": {"action": "login_encrypted", "data": data}},
                 lambda d: ad.expect_login(d.get("mac") or "", reply_room))


def logout(ad: Any, targets: list[dict]) -> dict:
    return _send(ad, targets, lambda d: {"command": "logout"})
