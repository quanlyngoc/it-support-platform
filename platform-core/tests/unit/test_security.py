from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from app.auth.ldap import ldap_bind
from app.security import crypto
from app.security.ipcheck import ip_allowed
from app.security.passwords import hash_password, verify_password
from app.security.tokens import hash_token, new_token


def test_argon2id():
    h = hash_password("Mat-khau@1")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Mat-khau@1") == (True, False)
    assert verify_password(h, "sai")[0] is False
    assert verify_password("", "x")[0] is False
    assert verify_password("pbkdf2:sha256:xxx", "x")[0] is False


def test_token_chi_luu_ban_bam():
    t = new_token()
    assert len(t) >= 40 and hash_token(t) != t and len(hash_token(t)) == 64
    assert new_token() != t


def test_aes_gcm_ma_hoa_va_chong_sua():
    key = base64.b64encode(os.urandom(32)).decode()
    enc = crypto.encrypt("bi mat SMTP", key)
    assert enc.startswith("v1:") and crypto.decrypt(enc, key) == "bi mat SMTP"
    raw = bytearray(base64.b64decode(enc[3:]))
    raw[-1] ^= 1
    with pytest.raises(InvalidTag):
        crypto.decrypt("v1:" + base64.b64encode(bytes(raw)).decode(), key)


@pytest.mark.parametrize("ip,cidrs,ok", [
    ("10.6.44.5", None, True), ("10.6.44.5", [], True),
    ("10.6.44.5", ["10.6.44.0/24"], True), ("10.6.45.5", ["10.6.44.0/24"], False),
    ("10.6.45.5", ["10.6.44.0/24", "10.6.45.5"], True), ("", ["10.0.0.0/8"], False),
    ("khong-phai-ip", ["10.0.0.0/8"], False), ("10.1.1.1", ["rac", "10.0.0.0/8"], True),
])
def test_gioi_han_ip(ip, cidrs, ok):
    assert ip_allowed(ip, cidrs) is ok


def test_ldap_mat_khau_rong_luon_bi_tu_choi():
    # anonymous bind với mật khẩu rỗng luôn "thành công" ở LDAP -> phải chặn trước khi gọi máy chủ
    assert ldap_bind({"ldap.server": "ldap://khong-ton-tai.invalid"}, "u", "") is False
    assert ldap_bind({}, "u", "abc") is False
