"""Kiểm tra sống (dùng cho NSSM, Caddy, giám sát).

`/api/health` không chạm CSDL (rẻ, gọi dày được). `/api/health?db=1` thêm một lệnh `ping` tới MongoDB — dùng khi
cài/kiểm dịch vụ để chắc tài khoản chạy dịch vụ (LocalSystem) với tới được CSDL; lỗi CSDL trả 503 để script nhận ra.
"""
from __future__ import annotations

import time

from apiflask import APIBlueprint
from flask import current_app, request

bp = APIBlueprint("health", __name__, url_prefix="/api", tag="Hệ thống")


@bp.get("/health")
@bp.doc(summary="Core đang chạy (thêm ?db=1 để kiểm cả kết nối CSDL)")
def health():
    body: dict = {"ok": True, "service": "platform-core", "version": current_app.config["ITM_SETTINGS"].VERSION}
    if request.args.get("db") != "1":
        return body
    t0 = time.perf_counter()
    try:
        current_app.extensions["itm_db"].command("ping")
    except Exception as e:  # mọi lỗi CSDL đều phải hiện ra cho người kiểm, không chỉ lỗi mạng
        body.update(ok=False, db="loi", db_error=type(e).__name__)
        return body, 503
    body.update(db="ok", db_ms=round((time.perf_counter() - t0) * 1000))
    return body
