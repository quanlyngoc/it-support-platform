"""Vòng đời tổ chức tối thiểu ở Core (đầy đủ ở Platform-Master, GĐ11) và tạo người dùng."""
from __future__ import annotations

import re
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.database import Database

from app.security.passwords import hash_password
from app.tenants.refs import require_refs
from app.tenants.repo import AdUserRepo, PolicyRepo, TenantRepo, UserRepo

SUPER_ADMIN_POLICY = "Super Admin"
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,31}$")


class TenantError(ValueError):
    pass


def normalize_code(code: str) -> str:
    c = (code or "").strip().upper()
    if not _CODE_RE.match(c):
        raise TenantError("Mã tổ chức chỉ gồm chữ in hoa, số, '-' hoặc '_' (2–32 ký tự)")
    return c


def get_tenant_by_code(db: Database, code: str, active_only: bool = True) -> dict | None:
    q: dict = {"code": (code or "").strip().upper()}
    if active_only:
        q["status"] = "ACTIVE"
    return db.tenants.find_one(q)


def create_tenant(db: Database, code: str, name: str, timezone: str = "Asia/Ho_Chi_Minh") -> dict:
    code = normalize_code(code)
    if db.tenants.find_one({"code": code}):
        raise TenantError(f"Tổ chức {code} đã tồn tại")
    now = datetime.now(UTC)
    tenant = {"code": code, "name": name.strip(), "status": "ACTIVE", "settings": {"timezone": timezone},
              "created_at": now, "updated_at": now}
    tenant["_id"] = db.tenants.insert_one(tenant).inserted_id
    all_perm_ids = [p["_id"] for p in db.permissions.find({}, {"_id": 1})]
    PolicyRepo(db, tenant["_id"]).insert_one({
        "name": SUPER_ADMIN_POLICY, "description": "Toàn quyền, policy hệ thống (không sửa/xoá)", "system": True,
        "permission_ids": all_perm_ids, "room_ids": [], "created_at": now, "updated_at": now})
    return tenant


def super_admin_policy_id(db: Database, tenant_id: ObjectId) -> ObjectId:
    p = PolicyRepo(db, tenant_id).find_one({"name": SUPER_ADMIN_POLICY, "system": True})
    if not p:
        raise TenantError("Tổ chức chưa có policy Super Admin")
    return p["_id"]


def create_user(db: Database, tenant_id: ObjectId, username: str, *, password: str | None = None,
                user_type: str = "LOCAL", display_name: str = "", policy_ids: list[ObjectId] | None = None,
                allowed_ip_cidrs: list[str] | None = None, upn: str = "") -> dict:
    uname = (username or "").strip()
    if not uname:
        raise TenantError("Thiếu tên đăng nhập")
    if user_type not in ("LOCAL", "AD"):
        raise TenantError("user_type phải là LOCAL hoặc AD")
    lc = uname.lower()
    require_refs(db, tenant_id, policies=policy_ids)  # 4A.29: User.tenant_id == Policy.tenant_id
    if UserRepo(db, tenant_id).find_one({"username_lc": lc}) or AdUserRepo(db, tenant_id).find_one({"username_lc": lc}):
        raise TenantError(f"Tài khoản {uname} đã tồn tại")
    now = datetime.now(UTC)
    doc = {"username": uname, "username_lc": lc, "display_name": display_name or uname,
           "user_type": user_type, "is_active": True, "allowed_ip_cidrs": list(allowed_ip_cidrs or []),
           "room_ids": [], "policy_ids": list(policy_ids or []), "totp_enabled": False,
           "created_at": now, "updated_at": now, "last_login_at": None}
    if user_type == "LOCAL":
        if not password:
            raise TenantError("Tài khoản Local phải có mật khẩu")
        doc.update(password_hash=hash_password(password), must_change_password=False)
        repo: TenantRepo = UserRepo(db, tenant_id)
    else:  # AD: đăng ký trong ad_user_policies (đặc tả 4A.8), mật khẩu kiểm bằng LDAP
        doc.update(upn=upn or None)
        repo = AdUserRepo(db, tenant_id)
    doc["_id"] = repo.insert_one(doc).inserted_id
    return doc
