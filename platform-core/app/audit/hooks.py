"""Hook after_request: ghi nhật ký mọi request thay đổi dữ liệu của người dùng đã đăng nhập (kể cả Super Admin)."""
from __future__ import annotations

from flask import Flask, current_app, g, request

from app.audit.service import write_audit

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP = {"/api/auth/login", "/api/auth/logout"}  # đã ghi riêng trong dịch vụ xác thực


def _system_of(path: str) -> str:
    if path.startswith(("/api/hsk", "/internal/thu", "/hsk")):
        return "HSK"
    if path.startswith(("/api/thi", "/thi")):
        return "THI"
    return "LAB"


def register(app: Flask) -> None:
    @app.after_request
    def _audit(resp):
        ctx = getattr(g, "ctx", None)
        if ctx is not None and request.method in _MUTATING and request.path not in _SKIP:
            write_audit(current_app.extensions["itm_db"], ctx.tenant_id,
                        action=f"{request.method} {request.path}", actor=ctx.username, actor_user_id=ctx.user_id,
                        ip=getattr(g, "client_ip", ""), system=_system_of(request.path), status=resp.status_code)
        return resp
