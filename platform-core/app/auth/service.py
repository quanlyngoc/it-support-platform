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


def _tenant_settings(db: Database, tenant_id: ObjectId, prefix: str) -> dict:
    return {d["key"]: d.get("value") for d in SettingRepo(db, tenant_id).find({"key": {"$regex": f"^{prefix}"}})}


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

    user, kind = UserRepo(db, tid).find_one({"username_lc": lc}), "LOCAL"
    if user is None:
        user, kind = AdUserRepo(db, tid).find_one({"username_lc": lc}), "AD"
    if user is None or not user.get("is_active", True) or not password:
        raise fail("CREDENTIALS")

    if kind == "LOCAL":
        ok, rehash = verify_password(user.get("password_hash") or "", password)
        if not ok:
            raise fail("CREDENTIALS")
        if rehash:
            UserRepo(db, tid).update_by_id(user["_id"], {"$set": {"password_hash": hash_password(password)}})
    else:
        bind = ldap_bind or default_ldap_bind
        if not bind(_tenant_settings(db, tid, "ldap."), user.get("upn") or user["username"], password):
            raise fail("CREDENTIALS")

    perms, is_super, rooms = _effective(db, tid, user.get("policy_ids", []))

    if user.get("totp_enabled"):
        if not totp:
            raise AuthError("TOTP_REQUIRED")
        secret = crypto.decrypt(user["totp_secret_enc"], master_key_b64)
        if not pyotp.TOTP(secret).verify(totp.strip(), valid_window=1):
            raise fail("TOTP")

    if not is_super and not ip_allowed(ip, user.get("allowed_ip_cidrs")):
        raise fail("IP")

    token = new_token()
    th = hash_token(token)
    exp = now + timedelta(hours=ttl_hours)
    sid = SessionRepo(db, tid).insert_one({
        "user_id": user["_id"], "user_kind": kind, "username": user["username"], "tenant_code": tenant["code"],
        "permissions": sorted(perms), "is_super": is_super, "room_ids": list(rooms),
        "session_token_hash": th, "ip": ip, "created_at": now, "last_seen_at": now, "expires_at": exp,
        "is_active": True}).inserted_id
    if not is_super:  # một thiết bị/một thời điểm: phiên mới ghi đè, thiết bị cũ mất hiệu lực
        ActiveSessionRepo(db, tid).update_one(
            {"user_id": user["_id"]},
            {"$set": {"session_id": sid, "token_hash": th, "ip": ip, "created_at": now, "expires_at": exp}},
            upsert=True)
    repo = UserRepo(db, tid) if kind == "LOCAL" else AdUserRepo(db, tid)
    repo.update_by_id(user["_id"], {"$set": {"last_login_at": now}})
    write_audit(db, tid, action="LOGIN_OK", actor=user["username"], actor_user_id=user["_id"], ip=ip)

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
