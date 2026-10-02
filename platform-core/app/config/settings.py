"""Cấu hình Platform-Core, đọc từ biến môi trường (+ tệp .env).

Thứ tự: biến môi trường của tiến trình > tệp chỉ định bởi DOTENV_PATH > platform-core/.env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

CORE_ROOT = Path(__file__).resolve().parents[2]

# HOAN_BAO_MAT: khoá mặc định cho giai đoạn dựng thử; khi chạy thật bắt buộc đặt MASTER_KEY_B64 riêng.
_DEV_MASTER_KEY_B64 = "aXRzcC1kZXYta2V5LWNoaS1kdW5nLWtoaS1kdW5nLXRodQ=="


@dataclass(frozen=True)
class Settings:
    MONGO_URI: str
    MONGO_DB: str = "itm_core"
    MASTER_DB: str = "itm_master"
    HOST: str = "127.0.0.1"  # Caddy cùng máy → chỉ nghe nội bộ; Core ở máy riêng thì đặt HOST=0.0.0.0 + tường lửa
    PORT: int = 7009
    MASTER_KEY_B64: str = _DEV_MASTER_KEY_B64
    SESSION_TTL_HOURS: int = 12
    TRUSTED_PROXIES: tuple[str, ...] = ("127.0.0.1", "::1")
    ALLOWED_ORIGINS: str = "*"  # HOAN_BAO_MAT: siết lại theo địa chỉ Desktop khi chạy thật
    ASYNC_MODE: str = "gevent"
    VERSION: str = "3.0.0-dev"
    # Kho tệp của Core (bộ cài agent, giao/thu bài, truyền tệp) — chia theo mã tổ chức bên trong
    DATA_DIR: str = str(CORE_ROOT.parent / ".dev" / "data")
    # Bộ tương thích agent v2 (2.7.5.x): giao thức không xác thực agent → gắn cứng vào MỘT tổ chức
    LEGACY_TENANT_CODE: str = "PHENIKAA"
    LEGACY_ALLOWED_CIDRS: tuple[str, ...] = ()  # HOAN_BAO_MAT: rỗng = nhận mọi IP; chạy thật đặt dải IP phòng máy


def _load_env() -> None:
    path = os.getenv("DOTENV_PATH") or str(CORE_ROOT / ".env")
    if os.path.exists(path):
        load_dotenv(path, override=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_env()
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        raise RuntimeError("Thiếu MONGO_URI (đặt trong platform-core/.env hoặc biến môi trường)")
    proxies = tuple(p.strip() for p in os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if p.strip())
    return Settings(
        MONGO_URI=uri,
        MONGO_DB=os.getenv("MONGO_DB", "itm_core"),
        MASTER_DB=os.getenv("MASTER_DB", "itm_master"),
        HOST=os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1",
        PORT=int(os.getenv("PORT", "7009")),
        MASTER_KEY_B64=os.getenv("MASTER_KEY_B64", "") or _DEV_MASTER_KEY_B64,
        SESSION_TTL_HOURS=int(os.getenv("SESSION_TTL_HOURS", "12")),
        TRUSTED_PROXIES=proxies,
        ALLOWED_ORIGINS=os.getenv("ALLOWED_ORIGINS", "*"),
        ASYNC_MODE=os.getenv("ASYNC_MODE", "gevent"),
        DATA_DIR=os.getenv("DATA_DIR", "").strip() or str(CORE_ROOT.parent / ".dev" / "data"),
        LEGACY_TENANT_CODE=os.getenv("LEGACY_TENANT_CODE", "PHENIKAA").strip().upper() or "PHENIKAA",
        LEGACY_ALLOWED_CIDRS=_csv(os.getenv("LEGACY_ALLOWED_CIDRS", "")),
    )


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.replace(";", ",").split(",") if p.strip())
