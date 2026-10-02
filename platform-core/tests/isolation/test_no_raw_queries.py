"""Quét mã nguồn: cấm truy cập trực tiếp collection tenant-owned ngoài tầng repository (quy tắc AI 4–5)."""
from __future__ import annotations

import pathlib
import re

from app.db.collections import TENANT_OWNED

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
_COLS = "|".join(TENANT_OWNED)
PATTERNS = [
    re.compile(r"db\[\s*['\"](" + _COLS + r")['\"]\s*\]"),  # db["users"]
    re.compile(r"\bdb\.(" + _COLS + r")\b"),                 # db.users
]
# Được phép: tầng repository (tệp repo.py) và tầng khởi tạo CSDL (app/db) — nơi tạo collection/index/validator
ALLOWED = {"repo.py"}


def test_khong_co_truy_van_tran_ngoai_repo():
    bad = []
    for f in APP.rglob("*.py"):
        if f.name in ALLOWED or f.parent.name == "db":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if any(p.search(line) for p in PATTERNS):
                bad.append(f"{f.relative_to(APP.parent)}:{i}: {line.strip()}")
    assert not bad, "Truy vấn trần collection tenant-owned:\n" + "\n".join(bad)


def test_mau_quet_bat_duoc_vi_pham():
    assert any(p.search('x = db["computers"].find({})') for p in PATTERNS)
    assert any(p.search("db.users.find_one({})") for p in PATTERNS)
    assert not any(p.search("db.tenants.find_one({})") for p in PATTERNS)
