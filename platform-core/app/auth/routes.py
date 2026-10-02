"""API xác thực /api/auth/* (đặc tả §10, §50)."""
from __future__ import annotations

from apiflask import APIBlueprint, abort
from flask import current_app, g, request
from pydantic import BaseModel, Field

from app.auth import service
from app.rbac.perms import login_required
from app.tenants.context import current

bp = APIBlueprint("auth", __name__, url_prefix="/api/auth", tag="Đăng nhập")


class LoginIn(BaseModel):
    tenant_code: str = Field(min_length=2, max_length=32, description="Mã tổ chức, vd. PHENIKAA")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)
    totp: str | None = Field(default=None, max_length=10)


def _bearer() -> str:
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def _ctx_json(ctx) -> dict:
    return {"tenant_code": ctx.tenant_code, "user_id": str(ctx.user_id), "username": ctx.username,
            "is_super": ctx.is_super, "permissions": sorted(ctx.permissions),
            "room_ids": [str(r) for r in ctx.room_ids]}


@bp.post("/login")
@bp.input(LoginIn)
@bp.doc(summary="Đăng nhập bằng mã tổ chức + tài khoản + mật khẩu (+ TOTP)")
def login(json_data: LoginIn):
    s = current_app.config["ITM_SETTINGS"]
    try:
        r = service.login(current_app.extensions["itm_db"], tenant_code=json_data.tenant_code,
                          username=json_data.username, password=json_data.password, totp=json_data.totp,
                          ip=g.client_ip, master_key_b64=s.MASTER_KEY_B64, ttl_hours=s.SESSION_TTL_HOURS,
                          ldap_bind=current_app.config.get("ITM_LDAP_BIND"))
    except service.AuthError as e:
        abort(401, e.message, extra_data={"code": e.code})
    return {"token": r.token, "expires_at": r.expires_at.isoformat(), "user": r.user, "session": _ctx_json(r.ctx)}


@bp.post("/logout")
@login_required
@bp.doc(summary="Đăng xuất phiên hiện tại")
def logout():
    service.logout(current_app.extensions["itm_db"], current(), _bearer(), ip=g.client_ip)
    return {"ok": True}


@bp.get("/me")
@login_required
@bp.doc(summary="Thông tin phiên hiện tại")
def me():
    return _ctx_json(current())


def load_context() -> None:
    """before_request: dựng g.ctx từ token Bearer. Tổ chức CHỈ lấy từ phiên, bỏ qua mọi header/tham số tổ chức."""
    g.client_ip = _client_ip()
    g.ctx = service.resolve(current_app.extensions["itm_db"], _bearer())


def _client_ip() -> str:
    from app.utils.clientip import client_ip

    return client_ip(request, current_app.config["ITM_SETTINGS"].TRUSTED_PROXIES)
