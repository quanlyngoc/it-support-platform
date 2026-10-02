"""Đọc (CHỈ ĐỌC) cấu hình hệ cũ cần cho cảnh báo 0.7 và in JSON ra stdout — dùng bởi cai_dat_ops.ps1 để điền
kho bí mật D:\\ITSupportPlatformSecrets, người vận hành không phải chép tay bí mật.

- Telegram: settings.telegram_bot_token / telegram_chat_id trong D:\\NetworkInventory\\database.db (mở mode=ro).
- Token nội bộ: theo đúng thứ tự hub cũ dùng (app.py `_internal_token`): biến môi trường INTERNAL_API_TOKEN →
  settings.internal_api_token → giá trị mặc định ghi trong mã app.py. (02/10/2026: hub không đặt env/settings nên
  đang dùng giá trị mặc định — đã ghi ở "Hoãn bảo mật".)
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sqlite3
import sys

GOC = pathlib.Path(r"D:\NetworkInventory")


def doc(goc: pathlib.Path = GOC) -> dict:
    c = sqlite3.connect(f"file:{(goc / 'database.db').as_posix()}?mode=ro", uri=True, timeout=10)
    try:
        cfg = {k: (v or "").strip() for k, v in c.execute(
            "select key, value from settings "
            "where key in ('telegram_bot_token', 'telegram_chat_id', 'internal_api_token')")}
    finally:
        c.close()
    tok = os.getenv("INTERNAL_API_TOKEN", "").strip() or cfg.get("internal_api_token", "")
    if not tok:
        m = re.search(r"def _internal_token\(\):\s*\n\s*return .*?'([0-9a-f]{32,})'",
                      (goc / "app.py").read_text(encoding="utf-8"))
        tok = m.group(1) if m else ""
    return {"telegram_token": cfg.get("telegram_bot_token", ""), "telegram_chat": cfg.get("telegram_chat_id", ""),
            "internal_token": tok}


if __name__ == "__main__":
    sys.stdout.write(json.dumps(doc()))
