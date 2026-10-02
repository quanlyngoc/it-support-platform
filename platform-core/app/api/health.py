"""Kiểm tra sống (dùng cho NSSM, Caddy, giám sát)."""
from __future__ import annotations

from apiflask import APIBlueprint
from flask import current_app

bp = APIBlueprint("health", __name__, url_prefix="/api", tag="Hệ thống")


@bp.get("/health")
@bp.doc(summary="Core đang chạy")
def health():
    return {"ok": True, "service": "platform-core", "version": current_app.config["ITM_SETTINGS"].VERSION}
