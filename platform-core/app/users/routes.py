"""API Quản trị nền tảng /api/admin/* (Sổ tay 8.3).

Quyền theo catalog (thay "role admin" của hệ cũ): xem người dùng / phiên `user.view` · tạo Local
`local_user.create` · thêm AD `ad_user.add` · sửa `user.edit` · khoá/mở + đá phiên `user.toggle` · xoá `user.delete`
(hoặc `local_user.delete` / `ad_user.delete` đúng loại) · policy `policy.create` / `policy.edit` · nhật ký
`audit.view` · cấu hình đăng nhập (LDAP, SSO) + thông tin hệ thống `system.configure`. Kênh email/Telegram ở
`/api/settings/alerts` (8.2).

Đối chiếu hệ cũ: `/settings/api/users|user_add|user_edit|user_toggle|user_delete` + `ad_users|ad_user_save|
ad_user_toggle|ad_user_delete` → `/api/admin/users*` · `permissions|policies|policy_save|policy_delete` →
`/api/admin/permissions`, `/api/admin/policies*` · `online_users` → `/api/admin/sessions` (+ đá phiên) · `audit_logs` →
`/api/admin/audit` · `ldap_config|ldap_save|ldap_test` → `/api/admin/auth-config*` (+ công tắc LDAP, SSO mới) ·
`network_config` → `/api/admin/system` (chỉ xem — cổng/proxy của Core đặt bằng biến môi trường dịch vụ).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, Field

from app.auth import ldap, methods, sso
from app.auth.routes import default_redirect
from app.config.settings import _DEV_MASTER_KEY_B64
from app.rbac.perms import login_required, require_perm
from app.tenants.context import current
from app.users import service as svc

bp = APIBlueprint("admin", __name__, url_prefix="/api/admin", tag="Quản trị")


def _db():
    return current_app.extensions["itm_db"]


def _s():
    return current_app.config["ITM_SETTINGS"]


def _run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (svc.LoiQT, methods.LoiCauHinh) as e:
        abort(getattr(e, "code", 400), str(e))


def _need_any(*codes: str) -> None:
    ctx = current()
    if not any(ctx.can(c) for c in codes):
        abort(403, "Không đủ quyền", extra_data={"code": "FORBIDDEN", "required": list(codes)})


# ====================================================================== người dùng
@bp.get("/users")
@require_perm("user.view")
@bp.doc(summary="Người dùng Local + AD đã đăng ký (kèm policy, trạng thái, giới hạn IP)")
def users():
    items = svc.list_users(_db(), current())
    return {"items": items, "total": len(items)}


class UserIn(BaseModel):
    user_type: Literal["LOCAL", "AD"] = "LOCAL"
    username: str = Field(min_length=1, max_length=128, description="AD: chỉ gõ tên — tự ghép @domain của LDAP")
    display_name: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=512, description="Local: bắt buộc, ≥ 6 ký tự")
    email: str = Field(default="", max_length=200, description="Dùng để ghép tài khoản khi đăng nhập SSO")
    phone: str = Field(default="", max_length=30)
    policy_ids: list[str] = Field(default_factory=list, max_length=20)
    allowed_ip_cidrs: list[str] = Field(default_factory=list, max_length=50, description="Rỗng = mọi nơi")
    is_active: bool = True


@bp.post("/users")
@login_required
@bp.input(UserIn)
@bp.doc(summary="Tạo tài khoản Local (local_user.create) hoặc đăng ký tài khoản AD (ad_user.add)")
def user_create(json_data: UserIn):
    _need_any("local_user.create" if json_data.user_type == "LOCAL" else "ad_user.add")
    return _run(svc.create_user, _db(), current(), json_data.model_dump()), 201


class UserEdit(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    password: str | None = Field(default=None, max_length=512, description="Local: để trống = giữ nguyên")
    policy_ids: list[str] | None = Field(default=None, max_length=20)
    allowed_ip_cidrs: list[str] | None = Field(default=None, max_length=50)
    is_active: bool | None = None


@bp.put("/users/<user_id>")
@require_perm("user.edit")
@bp.input(UserEdit)
@bp.doc(summary="Sửa tài khoản (không tự đổi policy / trạng thái / giới hạn IP của chính mình)")
def user_edit(user_id: str, json_data: UserEdit):
    d = json_data.model_dump()
    if d.get("is_active") is not None and not current().can("user.toggle"):
        d["is_active"] = None  # khoá / mở là quyền riêng
    return _run(svc.update_user, _db(), current(), user_id, d)


class ActiveIn(BaseModel):
    is_active: bool


@bp.post("/users/<user_id>/active")
@require_perm("user.toggle")
@bp.input(ActiveIn)
@bp.doc(summary="Khoá / mở tài khoản (có hiệu lực ngay, kể cả phiên đang mở)")
def user_active(user_id: str, json_data: ActiveIn):
    ctx = current()
    me = str(ctx.user_id) == user_id
    if me:
        abort(403, "Không thể tự khoá / mở tài khoản của chính mình")
    return _run(svc.update_user, _db(), ctx, user_id, {"is_active": json_data.is_active})


@bp.delete("/users/<user_id>")
@login_required
@bp.doc(summary="Xoá tài khoản Local / gỡ đăng ký AD (đăng xuất mọi phiên của tài khoản đó)")
def user_delete(user_id: str):
    kind = _run(svc.kind_of, _db(), current(), user_id)
    _need_any("user.delete", "local_user.delete" if kind == "LOCAL" else "ad_user.delete")
    _run(svc.delete_user, _db(), current(), user_id)
    return {"ok": True}


# ====================================================================== quyền + policy
@bp.get("/permissions")
@login_required
@bp.doc(summary="Catalog quyền (nhóm theo chức năng) để tick khi tạo / sửa policy")
def permissions():
    _need_any("policy.create", "policy.edit", "user.view")
    return {"items": svc.permissions(_db())}


@bp.get("/policies")
@login_required
@bp.doc(summary="Policy của tổ chức: quyền, phòng giới hạn, số người đang gán")
def policies():
    _need_any("policy.create", "policy.edit", "user.view")
    items = svc.list_policies(_db(), current())
    return {"items": items, "total": len(items)}


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=200)
    room_ids: list[str] = Field(default_factory=list, max_length=500, description="Rỗng = mọi phòng")


@bp.post("/policies")
@require_perm("policy.create")
@bp.input(PolicyIn)
@bp.doc(summary="Tạo policy")
def policy_create(json_data: PolicyIn):
    d = json_data
    return _run(svc.save_policy, _db(), current(), None, name=d.name, description=d.description,
                codes=d.permissions, room_ids=d.room_ids), 201


@bp.put("/policies/<policy_id>")
@require_perm("policy.edit")
@bp.input(PolicyIn)
@bp.doc(summary="Sửa policy (policy hệ thống chỉ xem) — có hiệu lực từ lần đăng nhập sau của người được gán")
def policy_edit(policy_id: str, json_data: PolicyIn):
    d = json_data
    return _run(svc.save_policy, _db(), current(), policy_id, name=d.name, description=d.description,
                codes=d.permissions, room_ids=d.room_ids)


@bp.delete("/policies/<policy_id>")
@require_perm("policy.edit")
@bp.doc(summary="Xoá policy (không xoá policy hệ thống / đang gán)")
def policy_delete(policy_id: str):
    _run(svc.delete_policy, _db(), current(), policy_id)
    return {"ok": True}


# ====================================================================== phiên đang mở
@bp.get("/sessions")
@require_perm("user.view")
@bp.doc(summary="Người đang đăng nhập (hoạt động trong 15 phút)")
def sessions():
    items = svc.sessions(_db(), current())
    return {"items": items, "total": len(items)}


@bp.delete("/sessions/<session_id>")
@require_perm("user.toggle")
@bp.doc(summary="Đăng xuất một phiên đang mở (có hiệu lực ngay)")
def session_kick(session_id: str):
    _run(svc.kick, _db(), current(), session_id)
    return {"ok": True}


# ====================================================================== nhật ký hệ thống
class AuditQ(BaseModel):
    system: Literal["LAB", "HSK", "THI"] | None = None
    q: str | None = Field(default=None, max_length=64)
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=300, ge=1, le=2000)


def _day(d: date | None) -> datetime | None:
    return datetime.combine(d, time.min).astimezone().astimezone(UTC) if d else None


@bp.get("/audit")
@require_perm("audit.view")
@bp.input(AuditQ, location="query")
@bp.doc(summary="Nhật ký hệ thống (lọc theo hệ LAB / HSK / THI + từ khoá + khoảng ngày) — giữ 180 ngày")
def audit(query_data: AuditQ):
    qd = query_data
    items = svc.audit(_db(), current(), system=qd.system, q=qd.q, since=_day(qd.date_from),
                      until=_day(qd.date_to + timedelta(days=1)) if qd.date_to else None, limit=qd.limit)
    return {"items": items, "total": len(items)}


# ====================================================================== cơ chế đăng nhập (LDAP + SSO)
@bp.get("/auth-config")
@require_perm("system.configure")
@bp.doc(summary="Cấu hình đăng nhập: Local (luôn bật), LDAP, SSO — bí mật chỉ trả mặt nạ")
def auth_config():
    return methods.public(_db(), current().tenant_id, _s().MASTER_KEY_B64, default_redirect())


class LdapIn(BaseModel):
    enabled: bool | None = Field(default=None, description="Công tắc LDAP: tắt = AD không đăng nhập bằng mật khẩu")
    server: str | None = Field(default=None, max_length=300, description="ldaps://<ip>:636 · ldap://<ip>:389 · <ip>")
    domain: str | None = Field(default=None, max_length=200)
    base_dn: str | None = Field(default=None, max_length=300)
    bind_user: str | None = Field(default=None, max_length=200)
    bind_pass: str | None = Field(default=None, max_length=512, description="Để trống = giữ nguyên")
    clear_bind_pass: bool = False


@bp.put("/auth-config/ldap")
@require_perm("system.configure")
@bp.input(LdapIn)
@bp.doc(summary="Lưu cấu hình LDAP / bật-tắt LDAP")
def auth_config_ldap(json_data: LdapIn):
    tid = current().tenant_id
    _run(methods.save_ldap, _db(), tid, _s().MASTER_KEY_B64, json_data.model_dump())
    return methods.public(_db(), tid, _s().MASTER_KEY_B64, default_redirect())


class LdapTestIn(LdapIn):
    test_user: str | None = Field(default=None, max_length=200, description="Thử bằng tài khoản này thay bind user")
    test_password: str | None = Field(default=None, max_length=512)


@bp.post("/auth-config/ldap/test")
@require_perm("system.configure")
@bp.input(LdapTestIn)
@bp.doc(summary="Kiểm tra kết nối LDAP (dùng giá trị đang gõ, thiếu thì giá trị đã lưu) — báo đúng mã lỗi AD")
def auth_config_ldap_test(json_data: LdapTestIn):
    d = json_data
    cfg = methods.ldap_config(_db(), current().tenant_id, _s().MASTER_KEY_B64)
    server = d.server if d.server is not None else cfg["server"]
    domain = d.domain if d.domain is not None else cfg["domain"]
    if d.test_user:
        user, pw = ldap.principal_of(d.test_user, domain), d.test_password or ""
    else:
        user = d.bind_user if d.bind_user is not None else cfg["bind_user"]
        pw = d.bind_pass or cfg["bind_pass"]
    ok, msg = ldap.test_bind(server, user, pw)
    return {"ok": ok, "message": msg}


class SsoIn(BaseModel):
    enabled: bool | None = Field(default=None, description="Công tắc SSO: tắt = ẩn nút SSO, từ chối mọi đăng nhập SSO")
    provider_name: str | None = Field(default=None, max_length=60, description="Nhãn nút, vd. Microsoft 365")
    issuer: str | None = Field(default=None, max_length=500,
                               description="vd. https://login.microsoftonline.com/<tenant-id>/v2.0")
    client_id: str | None = Field(default=None, max_length=200)
    client_secret: str | None = Field(default=None, max_length=1000, description="Để trống = giữ nguyên")
    clear_client_secret: bool = False
    scopes: str | None = Field(default=None, max_length=300)
    username_claim: str | None = Field(default=None, max_length=60)
    allowed_domains: str | None = Field(default=None, max_length=300, description="Rỗng = mọi tên miền")
    redirect_uri: str | None = Field(default=None, max_length=500, description="Rỗng = tự suy từ địa chỉ Core")


@bp.put("/auth-config/sso")
@require_perm("system.configure")
@bp.input(SsoIn)
@bp.doc(summary="Lưu cấu hình SSO (OpenID Connect) / bật-tắt SSO")
def auth_config_sso(json_data: SsoIn):
    tid = current().tenant_id
    _run(methods.save_sso, _db(), tid, _s().MASTER_KEY_B64, json_data.model_dump())
    return methods.public(_db(), tid, _s().MASTER_KEY_B64, default_redirect())


@bp.post("/auth-config/sso/test")
@require_perm("system.configure")
@bp.input(SsoIn)
@bp.doc(summary="Kiểm tra cấu hình SSO: đọc tài liệu OpenID của nhà cung cấp")
def auth_config_sso_test(json_data: SsoIn):
    cfg = methods.sso_config(_db(), current().tenant_id, _s().MASTER_KEY_B64)
    if json_data.issuer is not None:
        cfg["issuer"] = json_data.issuer.strip()
    if json_data.client_id is not None:
        cfg["client_id"] = json_data.client_id.strip()
    try:
        return {"ok": True, "message": sso.test_config(cfg)}
    except sso.LoiSSO as e:
        return {"ok": False, "message": str(e)}


# ====================================================================== thông tin hệ thống (chỉ xem)
@bp.get("/system")
@require_perm("system.configure")
@bp.doc(summary="Thông tin Core đang chạy (cổng, CSDL, kho tệp, agent v2) — đổi bằng biến môi trường dịch vụ")
def system_info():
    s = _s()
    return {"version": s.VERSION, "host": s.HOST, "port": s.PORT, "mongo_db": s.MONGO_DB, "data_dir": s.DATA_DIR,
            "session_ttl_hours": s.SESSION_TTL_HOURS, "trusted_proxies": list(s.TRUSTED_PROXIES),
            "allowed_origins": s.ALLOWED_ORIGINS, "legacy_tenant_code": s.LEGACY_TENANT_CODE,
            "legacy_allowed_cidrs": list(s.LEGACY_ALLOWED_CIDRS), "vnc_relay": s.VNC_RELAY_PUBLIC,
            "dev_master_key": s.MASTER_KEY_B64 == _DEV_MASTER_KEY_B64,  # HOAN_BAO_MAT: còn khoá chủ mặc định
            "sso_redirect_default": default_redirect()}
