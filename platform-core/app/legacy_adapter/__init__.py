"""Bộ tương thích agent v2 (2.7.5.x) — Core trả lời agent cũ đúng như hub cũ.

Sổ tay 3.3; hợp đồng: tests/contract_v2/HOP_DONG.md.
"""
from __future__ import annotations

from typing import Any

from flask import Flask
from pymongo.database import Database

from app.config.settings import Settings
from app.legacy_adapter.adapter import LegacyAdapter
from app.legacy_adapter.fastpath import FastPath


def init_app(app: Flask, db: Database, settings: Settings, socketio: Any) -> LegacyAdapter:
    from app.legacy_adapter import socket_handlers  # noqa: F401  — đăng ký handler socket lúc import
    from app.legacy_adapter.api import bp as api_bp
    from app.legacy_adapter.http_routes import bp as http_bp

    ad = LegacyAdapter(db, settings, socketio, app.extensions.get("storage"))
    app.extensions["legacy"] = ad
    app.register_blueprint(http_bp)
    app.register_blueprint(api_bp)
    # /update + /check_command/<mac> đi đường nhanh, không qua Flask (thử tải: xem fastpath.py)
    app.wsgi_app = FastPath(app.wsgi_app, ad, settings.TRUSTED_PROXIES)  # type: ignore[method-assign]
    return ad
