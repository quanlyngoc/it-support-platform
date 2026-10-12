"""Xác thực: đăng nhập (Local/AD/TOTP), kiểm phiên, đăng xuất.

Mang các luật đã chạy ổn của hệ cũ: một thiết bị/một thời điểm (thiết bị mới đá thiết bị cũ, Super Admin miễn trừ),
giới hạn IP theo tài khoản (nghiêm ngặt), quyền chụp vào phiên lúc đăng nhập. Thêm tầng tổ chức (mã tổ chức).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pyotp
from bson import ObjectId
from pymongo.database import Database

from app.audit.service import write_audit
from app.auth.ldap import ldap_bind as default_ldap_bind
from app.auth.methods import ldap_enabled
from app.auth.repo import ActiveSessionRepo, SessionRepo, find_session_by_token_hash
from app.security import crypto
from app.security.ipcheck import ip_allowed
from app.security.passwords import hash_password, verify_password
from app.security.tokens import hash_token, new_token
from app.tenants.context import Ctx
from app.tenants.repo import AdUserRepo, PolicyRepo, SettingRepo, UserRepo
from app.tenants.service import SUPER_ADMIN_POLICY, get_tenant_by_code

LdapBind = Callable[[dict, str, str], bool]

MESSAGES = {
    "TENANT": "Mã tổ chức không đúng hoặc tổ chức đang bị khoá",
    "CREDENTIALS": "Sai tài khoản hoặc mật khẩu",
    "TOTP_REQUIRED": "Tài khoản yêu cầu mã xác thực 2 lớp (TOTP)",
    "TOTP": "Mã xác thực 2 lớp không đúng",
    "IP": "Tài khoản không được phép đăng nhập từ địa chỉ IP này",
    "LDAP_OFF": "Đăng nhập tài khoản AD bằng mật khẩu (LDAP) đang tắt — dùng nút đăng nhập SSO hoặc liên hệ quản trị",
    "OLD_PASSWORD": "Mật khẩu hiện tại không đúng",
    "WEAK_PASSWORD": "Mật khẩu mới tối thiểu 6 ký tự",
    "NOT_LOCAL": "Tài khoản AD đổi mật khẩu trong AD, không đổi ở đây",
}


class AuthError(Exception):
    def __init__(self, code: str):
        super().__init__(MESSAGES.get(code, code))
        self.code = code
        self.message = MESSAGES.get(code, code)


@dataclass
class LoginResult:
    token: str
    expires_at: datetime
    ctx: Ctx
    user: dict


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _effective(db: Database, tenant_id: ObjectId, policy_ids: list) -> tuple[frozenset[str], bool, tuple]:
    policies = list(PolicyRepo(db, tenant_id).find({"_id": {"$in": list(policy_ids or [])}}))
    is_super = any(p.get("system") and p.get("name") == SUPER_ADMIN_POLICY for p in policies)
    perm_ids = {pid for p in policies for pid in p.get("permission_ids", [])}
    codes = frozenset(d["code"] for d in db.permissions.find({"_id": {"$in": list(perm_ids)}}, {"code": 1}))
    rooms = tuple(sorted({r for p in policies for r in p.get("room_ids", [])}, key=str))
    return codes, is_super, rooms


def find_ad_user(db: Database, tid: ObjectId, name: str, domain: str = "") -> dict | None:
    """Tài khoản AD đã đăng ký: khớp tên đăng nhập, UPN, hoặc tên ngắn + @domain (người dùng gõ "anh.nguyen" mà quản trị
    đăng ký "anh.nguyen@phenikaamec.local" — hệ cũ `_get_ad_user_rec` cũng khớp cả hai)."""
    lc = (name or "").strip().lower()
    if not lc:
        return None
    cands = [lc]
    d = (domain or "").strip().lstrip("@").lower()
    if d and "@" not in lc and "\\" not in lc:
        cands.append(f"{lc}@{d}")
    return AdUserRepo(db, tid).find_one({"$or": [{"username_lc": {"$in": cands}}, {"upn_lc": {"$in": cands}}]})


def _tenant_settings(db: Database, tenant_id: ObjectId, prefix: str) -> dict:
    return {d["key"]: d.get("value") for d in SettingRepo(db, tenant_id).find({"key": {"$regex": f"^{prefix}"}})}


def ctx_json(ctx: Ctx) -> dict:
    return {"tenant_code": ctx.tenant_code, "user_id": str(ctx.user_id), "username": ctx.username,
            "is_super": ctx.is_super, "permissions": sorted(ctx.permissions),
            "room_ids": [str(r) for r in ctx.room_ids]}


def public_user(user: dict, kind: str) -> dict:
    return {"id": str(user["_id"]), "username": user["username"], "display_name": user.get("display_name") or "",
            "user_type": kind}


# ---------------- Đăng nhập ----------------
def login(db: Database, *, tenant_code: str, username: str, password: str, totp: str | None = None, ip: str = "",
          master_key_b64: str, ttl_hours: int = 12, ldap_bind: LdapBind | None = None,
          now: datetime | None = None) -> LoginResult:
    now = now or datetime.now(UTC)
    tenant = get_tenant_by_code(db, tenant_code)
    if not tenant:
        raise AuthError("TENANT")
    tid = tenant["_id"]
    lc = (username or "").strip().lower()

    def fail(code: str) -> AuthError:
        write_audit(db, tid, action="LOGIN_FAIL", actor=lc, detail=code, ip=ip)
        return AuthError(code)

    ldap_cfg = _tenant_settings(db, tid, "ldap.")
    user, kind = UserRepo(db, tid).find_one({"username_lc": lc}), "LOCAL"
    if user is None:
        user, kind = find_ad_user(db, tid, lc, str(ldap_cfg.get("ldap.domain") or "")), "AD"
    if user is None or not user.get("is_active", True) or not password:
        raise fail("CREDENTIALS")

    if kind == "LOCAL":
        ok, rehash = verify_password(user.get("password_hash") or "", password)
        if not ok:
            raise fail("CREDENTIALS")
        if rehash:
            UserRepo(db, tid).update_by_id(user["_id"], {"$set": {"password_hash": hash_password(password)}})
    else:
        if not ldap_enabled(ldap_cfg):  # công tắc LDAP tắt → không gọi AD (Sổ tay 8.3 + yêu cầu 12/10/2026)
            raise fail("LDAP_OFF")
        bind = ldap_bind or default_ldap_bind
        if not bind(ldap_cfg, user.get("upn") or user["username"], password):
            raise fail("CREDENTIALS")

    if user.get("totp_enabled"):
        if not totp:
            raise AuthError("TOTP_REQUIRED")
        secret = crypto.decrypt(user["totp_secret_enc"], master_key_b64)
        if not pyotp.TOTP(secret).verify(totp.strip(), valid_window=1):
            raise fail("TOTP")

    return issue_session(db, tenant, user, kind, ip=ip, ttl_hours=ttl_hours, now=now, method=kind)


def issue_session(db: Database, tenant: dict, user: dict, kind: str, *, ip: str, ttl_hours: int, now: datetime,
                  method: str) -> LoginResult:
    """Bước chung sau khi ĐÃ xác thực danh tính (mật khẩu / LDAP / SSO): giới hạn IP, cấp phiên, một thiết bị."""
    tid = tenant["_id"]
    perms, is_super, rooms = _effective(db, tid, user.get("policy_ids", []))
    if not is_super and not ip_allowed(ip, user.get("allowed_ip_cidrs")):
        write_audit(db, tid, action="LOGIN_FAIL", actor=user["username"], detail=f"IP ({method})", ip=ip)
        raise AuthError("IP")

    token = new_token()
    th = hash_token(token)
    exp = now + timedelta(hours=ttl_hours)
    sid = SessionRepo(db, tid).insert_one({
        "user_id": user["_id"], "user_kind": kind, "username": user["username"], "tenant_code": tenant["code"],
        "permissions": sorted(perms), "is_super": is_super, "room_ids": list(rooms),
        "session_token_hash": th, "ip": ip, "created_at": now, "last_seen_at": now, "expires_at": exp,
        "is_active": True, "method": method}).inserted_id
    if not is_super:  # một thiết bị/một thời điểm: phiên mới ghi đè, thiết bị cũ mất hiệu lực
        ActiveSessionRepo(db, tid).update_one(
            {"user_id": user["_id"]},
            {"$set": {"session_id": sid, "token_hash": th, "ip": ip, "created_at": now, "expires_at": exp}},
            upsert=True)
    repo = UserRepo(db, tid) if kind == "LOCAL" else AdUserRepo(db, tid)
    repo.update_by_id(user["_id"], {"$set": {"last_login_at": now}})
    write_audit(db, tid, action="LOGIN_OK", actor=user["username"], actor_user_id=user["_id"], ip=ip, detail=method)

    ctx = Ctx(tenant_id=tid, tenant_code=tenant["code"], user_id=user["_id"], username=user["username"],
              permissions=perms, room_ids=rooms, is_super=is_super, session_id=sid)
    return LoginResult(token=token, expires_at=exp, ctx=ctx, user=public_user(user, kind))


# ---------------- Kiểm phiên (có đệm RAM) ----------------
_CACHE: dict[str, tuple[Ctx, float]] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL_SECONDS = 15.0


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def resolve(db: Database, token: str | None, *, now: datetime | None = None) -> Ctx | None:
    """Token -> Ctx, hoặc None nếu phiên không hợp lệ/hết hạn/bị đá/tổ chức hoặc tài khoản bị khoá."""
    if not token:
        return None
    th = hash_token(token)
    mono = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(th)
        if hit and hit[1] > mono:
            return hit[0]
    ctx = _resolve_db(db, th, now or datetime.now(UTC))
    with _CACHE_LOCK:
        if ctx is None:
            _CACHE.pop(th, None)
        else:
            if len(_CACHE) > 5000:
                _CACHE.clear()
            _CACHE[th] = (ctx, mono + CACHE_TTL_SECONDS)
    return ctx


def _resolve_db(db: Database, th: str, now: datetime) -> Ctx | None:
    s = find_session_by_token_hash(db, th)
    if not s or _aware(s["expires_at"]) <= now:
        return None
    tid = s["tenant_id"]
    if not db.tenants.find_one({"_id": tid, "status": "ACTIVE"}, {"_id": 1}):
        return None
    repo = UserRepo(db, tid) if s.get("user_kind", "LOCAL") == "LOCAL" else AdUserRepo(db, tid)
    user = repo.get(s["user_id"], {"is_active": 1})
    if not user or not user.get("is_active", True):
        return None
    if not s.get("is_super"):
        act = ActiveSessionRepo(db, tid).find_one({"user_id": s["user_id"]}, {"token_hash": 1})
        if act and act.get("token_hash") != th:
            return None  # đã đăng nhập ở thiết bị khác
    if (now - _aware(s.get("last_seen_at") or now)).total_seconds() > 60:
        SessionRepo(db, tid).update_by_id(s["_id"], {"$set": {"last_seen_at": now}})
    return Ctx(tenant_id=tid, tenant_code=s.get("tenant_code", ""), user_id=s["user_id"], username=s["username"],
               permissions=frozenset(s.get("permissions", [])), room_ids=tuple(s.get("room_ids", [])),
               is_super=bool(s.get("is_super")), session_id=s["_id"])


def logout(db: Database, ctx: Ctx, token: str, ip: str = "") -> None:
    th = hash_token(token)
    now = datetime.now(UTC)
    SessionRepo(db, ctx.tenant_id).update_one({"session_token_hash": th},
                                              {"$set": {"is_active": False, "revoked_at": now}})
    ActiveSessionRepo(db, ctx.tenant_id).delete_one({"user_id": ctx.user_id, "token_hash": th})
    with _CACHE_LOCK:
        _CACHE.pop(th, None)
    write_audit(db, ctx.tenant_id, action="LOGOUT", actor=ctx.username, actor_user_id=ctx.user_id, ip=ip)


def revoke_session(db: Database, tid: ObjectId, session_id: ObjectId) -> dict | None:
    """Đá một phiên (quản trị bấm "Đăng xuất phiên này"): phiên mất hiệu lực NGAY (bỏ cả đệm RAM 15 s)."""
    s = SessionRepo(db, tid).find_one({"_id": session_id, "is_active": True})
    if s is None:
        return None
    th = s["session_token_hash"]
    SessionRepo(db, tid).update_by_id(session_id, {"$set": {"is_active": False, "revoked_at": datetime.now(UTC)}})
    ActiveSessionRepo(db, tid).delete_one({"user_id": s["user_id"], "token_hash": th})
    with _CACHE_LOCK:
        _CACHE.pop(th, None)
    return s


def revoke_user_sessions(db: Database, tid: ObjectId, user_id: ObjectId) -> int:
    """Mọi phiên của một tài khoản (xoá tài khoản / đổi mật khẩu bởi quản trị)."""
    n = 0
    for s in SessionRepo(db, tid).find({"user_id": user_id, "is_active": True}, {"_id": 1}):
        n += revoke_session(db, tid, s["_id"]) is not None
    return n


def change_password(db: Database, ctx: Ctx, old: str, new: str, ip: str = "") -> None:
    """Người dùng Local tự đổi mật khẩu (hệ cũ: /admin/change_password — nay cho MỌI tài khoản Local)."""
    user = UserRepo(db, ctx.tenant_id).get(ctx.user_id)
    if user is None:
        raise AuthError("NOT_LOCAL")
    if not verify_password(user.get("password_hash") or "", old or "")[0]:
        write_audit(db, ctx.tenant_id, action="PASSWORD_CHANGE_FAIL", actor=ctx.username, actor_user_id=ctx.user_id,
                    ip=ip)
        raise AuthError("OLD_PASSWORD")
    if len(new or "") < 6:
        raise AuthError("WEAK_PASSWORD")
    UserRepo(db, ctx.tenant_id).update_by_id(ctx.user_id, {"$set": {
        "password_hash": hash_password(new), "must_change_password": False, "password_changed_at": datetime.now(UTC)}})
    write_audit(db, ctx.tenant_id, action="PASSWORD_CHANGE", actor=ctx.username, actor_user_id=ctx.user_id, ip=ip)
