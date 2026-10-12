"""API xác thực /api/auth/* (đặc tả §10, §50) + SSO OpenID Connect + công tắc cơ chế đăng nhập (Sổ tay 8.3)."""
from __future__ import annotations

from apiflask import APIBlueprint, abort
from flask import current_app, g, make_response, request
from pydantic import BaseModel, Field

from app.auth import methods, service, sso
from app.auth.service import ctx_json
from app.rbac.perms import login_required
from app.tenants.context import current
from app.tenants.service import get_tenant_by_code

bp = APIBlueprint("auth", __name__, url_prefix="/api/auth", tag="Đăng nhập")


class LoginIn(BaseModel):
    tenant_code: str = Field(min_length=2, max_length=32, description="Mã tổ chức, vd. PHENIKAA")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)
    totp: str | None = Field(default=None, max_length=10)


def _bearer() -> str:
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def _db():
    return current_app.extensions["itm_db"]


def _s():
    return current_app.config["ITM_SETTINGS"]


@bp.post("/login")
@bp.input(LoginIn)
@bp.doc(summary="Đăng nhập bằng mã tổ chức + tài khoản + mật khẩu (+ TOTP) — Local, hoặc AD khi LDAP đang bật")
def login(json_data: LoginIn):
    s = _s()
    try:
        r = service.login(_db(), tenant_code=json_data.tenant_code,
                          username=json_data.username, password=json_data.password, totp=json_data.totp,
                          ip=g.client_ip, master_key_b64=s.MASTER_KEY_B64, ttl_hours=s.SESSION_TTL_HOURS,
                          ldap_bind=current_app.config.get("ITM_LDAP_BIND"))
    except service.AuthError as e:
        abort(401, e.message, extra_data={"code": e.code})
    return {"token": r.token, "expires_at": r.expires_at.isoformat(), "user": r.user, "session": ctx_json(r.ctx)}


@bp.post("/logout")
@login_required
@bp.doc(summary="Đăng xuất phiên hiện tại")
def logout():
    service.logout(_db(), current(), _bearer(), ip=g.client_ip)
    return {"ok": True}


@bp.get("/me")
@login_required
@bp.doc(summary="Thông tin phiên hiện tại")
def me():
    return ctx_json(current())


class PasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=6, max_length=512)


@bp.post("/password")
@login_required
@bp.input(PasswordIn)
@bp.doc(summary="Tự đổi mật khẩu (tài khoản Local) — hệ cũ /admin/change_password")
def change_password(json_data: PasswordIn):
    try:
        service.change_password(_db(), current(), json_data.old_password, json_data.new_password, ip=g.client_ip)
    except service.AuthError as e:
        abort(400, e.message, extra_data={"code": e.code})
    return {"ok": True}


# ====================================================================== cơ chế đăng nhập (công khai)
class TenantQ(BaseModel):
    tenant_code: str = Field(min_length=2, max_length=32)


@bp.get("/methods")
@bp.input(TenantQ, location="query")
@bp.doc(summary="Cơ chế đăng nhập đang bật của tổ chức (màn đăng nhập hiện nút SSO) — không cần đăng nhập")
def login_methods(query_data: TenantQ):
    t = get_tenant_by_code(_db(), query_data.tenant_code)
    if not t:
        return {"local": True, "ldap": False, "sso": False, "sso_label": ""}
    return methods.login_methods(_db(), t["_id"])


def default_redirect() -> str:
    """Redirect URI suy từ địa chỉ mà Desktop / trình duyệt đang gọi Core (sau Caddy: X-Forwarded-Proto/Host)."""
    proto, host = request.scheme, request.host
    if request.remote_addr in _s().TRUSTED_PROXIES:
        proto = request.headers.get("X-Forwarded-Proto", proto).split(",")[0].strip() or proto
        host = request.headers.get("X-Forwarded-Host", host).split(",")[0].strip() or host
    return f"{proto}://{host}/api/auth/sso/callback"


@bp.post("/sso/start")
@bp.input(TenantQ)
@bp.doc(summary="Bắt đầu đăng nhập SSO: trả login_id (giữ bí mật) + auth_url để mở trong trình duyệt")
def sso_start(json_data: TenantQ):
    try:
        return sso.start(_db(), json_data.tenant_code, _s().MASTER_KEY_B64, default_redirect())
    except sso.LoiSSO as e:
        abort(e.code, str(e))


@bp.get("/sso/callback")
@bp.doc(summary="Nhà cung cấp SSO chuyển trình duyệt về đây (trả trang HTML)")
def sso_callback():
    a = request.args
    s = _s()
    ok, msg = sso.callback(_db(), state=a.get("state", ""), code=a.get("code", ""), error=a.get("error", ""),
                           error_description=a.get("error_description", ""), master=s.MASTER_KEY_B64,
                           ttl_hours=s.SESSION_TTL_HOURS, ip=g.client_ip)
    resp = make_response(sso.page(ok, msg), 200 if ok else 400)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    return resp


class PollIn(TenantQ):
    login_id: str = Field(min_length=10, max_length=128)


@bp.post("/sso/poll")
@bp.input(PollIn)
@bp.doc(summary="Desktop hỏi kết quả SSO: pending / done (kèm token, MỘT lần) / error / expired")
def sso_poll(json_data: PollIn):
    try:
        return sso.poll(_db(), json_data.tenant_code, json_data.login_id, _s().MASTER_KEY_B64)
    except sso.LoiSSO as e:
        abort(e.code, str(e))


def load_context() -> None:
    """before_request: dựng g.ctx từ token Bearer. Tổ chức CHỈ lấy từ phiên, bỏ qua mọi header/tham số tổ chức."""
    g.client_ip = _client_ip()
    g.ctx = service.resolve(_db(), _bearer())


def _client_ip() -> str:
    from app.utils.clientip import client_ip

    return client_ip(request, _s().TRUSTED_PROXIES)
