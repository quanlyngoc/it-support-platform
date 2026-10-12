"""Quản trị nền tảng (Sổ tay 8.3) — người dùng Local/AD, policy + quyền, phiên đang mở, nhật ký hệ thống.

Luật mang từ hệ cũ (CHỈ ĐỌC: D:\\NetworkInventory\\app.py `/settings/api/*`):
- Không tự xoá / tự khoá / tự đổi policy / tự gỡ giới hạn IP của CHÍNH MÌNH (chống tự khoá mình ra ngoài, chống tự nâng
  quyền) — ép giữ giá trị đang lưu kể cả khi gọi thẳng API.
- Người KHÔNG phải Super Admin: không thấy policy "Super Admin", không gán được nó, không thao tác lên tài khoản đang
  mang nó (danh sách hiện "Quản trị viên" + khoá dòng).
- Policy hệ thống (Super Admin) chỉ xem; policy đang gán cho người dùng thì không xoá được.
- Quyền chụp vào phiên lúc đăng nhập → đổi policy có hiệu lực từ lần đăng nhập sau (giống hệ cũ). Khoá tài khoản có hiệu
  lực ngay (≤ 15 s đệm); quản trị đặt lại mật khẩu / xoá tài khoản → đăng xuất mọi phiên của tài khoản đó.
Thêm so với hệ cũ: không bao giờ xoá / khoá Super Admin CUỐI CÙNG còn hoạt động của tổ chức.
"""
from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime, timedelta
from re import escape
from typing import Any

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.auth.ldap import principal_of
from app.auth.service import revoke_session, revoke_user_sessions
from app.rbac.catalog import UnknownPermission, ids_for_codes
from app.security.passwords import hash_password
from app.tenants.context import Ctx
from app.tenants.refs import RefNotFound, require_refs
from app.tenants.repo import AdUserRepo, AuditRepo, PolicyRepo, SettingRepo, TenantRepo, UserRepo, repo_for
from app.tenants.service import SUPER_ADMIN_POLICY, TenantError
from app.tenants.service import create_user as tsvc_create_user

MASKED = "Quản trị viên"
_UNAME = re.compile(r"^[A-Za-z0-9._@\\-]{1,128}$")
NHOM = (("user.", "Người dùng"), ("local_user.", "Người dùng"), ("ad_user.", "Người dùng"), ("policy.", "Policy"),
        ("device.", "Phòng máy & thiết bị"), ("room_map.", "Phòng máy & thiết bị"), ("remote.", "Phòng máy & thiết bị"),
        ("agent.", "Phòng máy & thiết bị"), ("machine_events.", "Phòng máy & thiết bị"),
        ("incident.", "Sự cố & báo cáo"), ("report.", "Sự cố & báo cáo"), ("system.", "Hệ thống"),
        ("backup.", "Hệ thống"), ("audit.", "Hệ thống"))


class LoiQT(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


def _oid(s: object) -> ObjectId | None:
    try:
        return ObjectId(str(s))
    except Exception:
        return None


def _iso(v: object) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else None


# ====================================================================== quyền + policy
def permissions(db: Database) -> list[dict]:
    out = []
    for d in db.permissions.find({}, {"code": 1, "name": 1}).sort("code", 1):
        nhom = next((g for p, g in NHOM if d["code"].startswith(p)), "Khác")
        out.append({"code": d["code"], "name": d.get("name") or d["code"], "group": nhom})
    return out


def _pols(db: Database, tid: ObjectId) -> dict[ObjectId, dict]:
    return {p["_id"]: p for p in PolicyRepo(db, tid).find({})}


def _super_pid(pols: dict[ObjectId, dict]) -> ObjectId | None:
    return next((k for k, p in pols.items() if p.get("system") and p.get("name") == SUPER_ADMIN_POLICY), None)


def list_policies(db: Database, ctx: Ctx) -> list[dict]:
    tid = ctx.tenant_id
    codes = {d["_id"]: d["code"] for d in db.permissions.find({}, {"code": 1})}
    rooms = {r["_id"]: r["name"] for r in repo_for(db, tid, "rooms").find({}, {"name": 1})}
    dem: dict[ObjectId, int] = {}
    for repo in (UserRepo(db, tid), AdUserRepo(db, tid)):
        for u in repo.find({}, {"policy_ids": 1}):
            for pid in u.get("policy_ids") or []:
                dem[pid] = dem.get(pid, 0) + 1
    out = []
    for p in sorted(_pols(db, tid).values(), key=lambda p: (not p.get("system"), p["name"].lower())):
        if p.get("system") and p["name"] == SUPER_ADMIN_POLICY and not ctx.is_super:
            continue  # hệ cũ: policy Super Admin chỉ hiện với Super Admin
        out.append({"id": str(p["_id"]), "name": p["name"], "description": p.get("description") or "",
                    "system": bool(p.get("system")), "users": dem.get(p["_id"], 0),
                    "permissions": sorted(codes[i] for i in p.get("permission_ids") or [] if i in codes),
                    "room_ids": [str(r) for r in p.get("room_ids") or []],
                    "rooms": [rooms.get(r, "?") for r in p.get("room_ids") or []]})
    return out


def save_policy(db: Database, ctx: Ctx, policy_id: str | None, *, name: str, description: str, codes: list[str],
                room_ids: list[str]) -> dict:
    tid = ctx.tenant_id
    name = (name or "").strip()
    if not name:
        raise LoiQT("Chưa nhập tên policy")
    try:
        perm_ids = ids_for_codes(db, codes)
    except UnknownPermission as e:
        raise LoiQT(str(e)) from None
    rids = [r for r in (_oid(x) for x in room_ids) if r is not None]
    try:
        require_refs(db, tid, rooms=rids)
    except RefNotFound:
        raise LoiQT("Có phòng không thuộc tổ chức") from None
    if name.lower() == SUPER_ADMIN_POLICY.lower():
        raise LoiQT("Tên này dành cho policy hệ thống")
    repo = PolicyRepo(db, tid)
    now = datetime.now(UTC)
    body = {"name": name[:100], "description": (description or "").strip()[:500], "permission_ids": perm_ids,
            "room_ids": list(dict.fromkeys(rids)), "updated_at": now}
    try:
        if policy_id:
            pid = _oid(policy_id)
            cur = repo.find_one({"_id": pid}) if pid else None
            if cur is None:
                raise LoiQT("Không có policy này", 404)
            if cur.get("system"):
                raise LoiQT("Policy hệ thống (Super Admin) chỉ xem, không sửa được", 403)
            repo.update_by_id(cur["_id"], {"$set": body})
            return {"id": str(cur["_id"])}
        return {"id": str(repo.insert_one({**body, "system": False, "created_at": now}).inserted_id)}
    except DuplicateKeyError:
        raise LoiQT("Tên policy đã tồn tại", 409) from None


def delete_policy(db: Database, ctx: Ctx, policy_id: str) -> None:
    tid = ctx.tenant_id
    pid = _oid(policy_id)
    cur = PolicyRepo(db, tid).find_one({"_id": pid}) if pid else None
    if cur is None:
        raise LoiQT("Không có policy này", 404)
    if cur.get("system"):
        raise LoiQT("Không xoá được policy hệ thống (Super Admin)", 403)
    n = UserRepo(db, tid).count({"policy_ids": pid}) + AdUserRepo(db, tid).count({"policy_ids": pid})
    if n:
        raise LoiQT(f"Policy đang gán cho {n} người dùng — gỡ gán trước khi xoá", 409)
    PolicyRepo(db, tid).delete_by_id(cur["_id"])


# ====================================================================== người dùng
def _ips(raw: list[str] | None) -> list[str]:
    out = []
    for x in raw or []:
        x = str(x).strip()
        if not x:
            continue
        try:
            ipaddress.ip_network(x, strict=False)
        except ValueError:
            raise LoiQT(f"Địa chỉ / dải IP không hợp lệ: {x}") from None
        out.append(x)
    return out


def _is_super_user(u: dict, sp: ObjectId | None) -> bool:
    return sp is not None and sp in (u.get("policy_ids") or [])


def _find(db: Database, tid: ObjectId, user_id: str) -> tuple[dict, str, TenantRepo]:
    uid = _oid(user_id)
    if uid is not None:
        for kind, repo in (("LOCAL", UserRepo(db, tid)), ("AD", AdUserRepo(db, tid))):
            u = repo.find_one({"_id": uid})
            if u:
                return u, kind, repo
    raise LoiQT("Không có tài khoản này", 404)


def _public(u: dict, kind: str, ctx: Ctx, pols: dict[ObjectId, dict], sp: ObjectId | None) -> dict:
    sup = _is_super_user(u, sp)
    locked = sup and not ctx.is_super
    pids = [p for p in u.get("policy_ids") or [] if p in pols]
    return {"id": str(u["_id"]), "username": u["username"], "display_name": u.get("display_name") or "",
            "user_type": kind, "email": u.get("email") or "", "phone": u.get("phone") or "", "upn": u.get("upn") or "",
            "is_active": bool(u.get("is_active", True)), "totp_enabled": bool(u.get("totp_enabled")),
            "allowed_ip_cidrs": list(u.get("allowed_ip_cidrs") or []),
            "policy_ids": [] if locked else [str(p) for p in pids],
            "policies": [MASKED] if locked else [pols[p]["name"] for p in pids],
            "is_super": sup and ctx.is_super, "locked": locked, "is_self": u["_id"] == ctx.user_id,
            "last_login_at": _iso(u.get("last_login_at")), "created_at": _iso(u.get("created_at"))}


def list_users(db: Database, ctx: Ctx) -> list[dict]:
    tid = ctx.tenant_id
    pols = _pols(db, tid)
    sp = _super_pid(pols)
    out = []
    for kind, repo in (("LOCAL", UserRepo(db, tid)), ("AD", AdUserRepo(db, tid))):
        for u in repo.find({}, {"password_hash": 0, "totp_secret_enc": 0}).sort("username_lc", 1):
            out.append(_public(u, kind, ctx, pols, sp))
    return out


def _check_target(ctx: Ctx, u: dict, sp: ObjectId | None) -> None:
    if _is_super_user(u, sp) and not ctx.is_super:
        raise LoiQT("Không có quyền thao tác trên tài khoản Super Admin", 403)


def _check_pols(ctx: Ctx, ids: list[ObjectId], pols: dict[ObjectId, dict], sp: ObjectId | None) -> None:
    for p in ids:
        if p not in pols:
            raise LoiQT("Có policy không tồn tại")
        if p == sp and not ctx.is_super:
            raise LoiQT("Chỉ Super Admin mới được gán policy Super Admin", 403)


def _last_super(db: Database, tid: ObjectId, u: dict, sp: ObjectId | None) -> bool:
    """`u` là Super Admin cuối cùng còn hoạt động? (mất là tổ chức không ai quản trị được nữa)"""
    if not _is_super_user(u, sp):
        return False
    n = sum(repo.count({"policy_ids": sp, "is_active": {"$ne": False}, "_id": {"$ne": u["_id"]}})
            for repo in (UserRepo(db, tid), AdUserRepo(db, tid)))
    return n == 0


def _ldap_domain(db: Database, tid: ObjectId) -> str:
    d = SettingRepo(db, tid).find_one({"key": "ldap.domain"}, {"value": 1})
    return str((d or {}).get("value") or "")


def create_user(db: Database, ctx: Ctx, data: dict) -> dict:
    tid = ctx.tenant_id
    kind = data.get("user_type") or "LOCAL"
    pols = _pols(db, tid)
    sp = _super_pid(pols)
    pids = [p for p in (_oid(x) for x in data.get("policy_ids") or []) if p is not None]
    _check_pols(ctx, pids, pols, sp)
    uname = (data.get("username") or "").strip()
    if kind == "AD":
        uname = principal_of(uname, _ldap_domain(db, tid))  # hệ cũ: chỉ gõ tên, tự ghép @domain
        if not pids:
            raise LoiQT("Tài khoản AD phải chọn ít nhất một policy")
    if not _UNAME.match(uname):
        raise LoiQT("Tên đăng nhập chỉ gồm chữ không dấu, số và . _ @ - \\")
    pw = data.get("password") or ""
    if kind == "LOCAL" and len(pw) < 6:
        raise LoiQT("Mật khẩu tài khoản Local tối thiểu 6 ký tự")
    email = (data.get("email") or "").strip()
    try:
        doc = tsvc_create_user(db, tid, uname, password=pw if kind == "LOCAL" else None, user_type=kind,
                               display_name=(data.get("display_name") or "").strip(), policy_ids=pids,
                               allowed_ip_cidrs=_ips(data.get("allowed_ip_cidrs")), upn=uname if kind == "AD" else "")
    except TenantError as e:
        raise LoiQT(str(e), 409 if "đã tồn tại" in str(e) else 400) from None
    except RefNotFound:
        raise LoiQT("Có policy không thuộc tổ chức") from None
    extra = {"email": email, "email_lc": email.lower(), "phone": (data.get("phone") or "").strip()[:30],
             "is_active": bool(data.get("is_active", True))}
    if kind == "AD":
        extra["upn_lc"] = uname.lower()
    repo: TenantRepo = UserRepo(db, tid) if kind == "LOCAL" else AdUserRepo(db, tid)
    repo.update_by_id(doc["_id"], {"$set": extra})
    return _public({**doc, **extra}, kind, ctx, pols, sp)


def update_user(db: Database, ctx: Ctx, user_id: str, data: dict) -> dict:
    tid = ctx.tenant_id
    u, kind, repo = _find(db, tid, user_id)
    pols = _pols(db, tid)
    sp = _super_pid(pols)
    _check_target(ctx, u, sp)
    is_self = u["_id"] == ctx.user_id
    s: dict[str, Any] = {"updated_at": datetime.now(UTC)}
    for k in ("display_name", "phone"):
        if data.get(k) is not None:
            s[k] = str(data[k]).strip()[:100]
    if data.get("email") is not None:
        s["email"] = str(data["email"]).strip()[:200]
        s["email_lc"] = s["email"].lower()
    if not is_self:  # tự đổi policy / trạng thái / giới hạn IP của chính mình: bỏ qua (giữ giá trị đang lưu)
        if data.get("policy_ids") is not None:
            pids = [p for p in (_oid(x) for x in data["policy_ids"]) if p is not None]
            _check_pols(ctx, pids, pols, sp)
            if kind == "AD" and not pids:
                raise LoiQT("Tài khoản AD phải có ít nhất một policy")
            if _last_super(db, tid, u, sp) and sp not in pids:
                raise LoiQT("Không gỡ được policy Super Admin của Super Admin cuối cùng", 409)
            s["policy_ids"] = pids
        if data.get("allowed_ip_cidrs") is not None:
            s["allowed_ip_cidrs"] = _ips(data["allowed_ip_cidrs"])
        if data.get("is_active") is not None:
            if not data["is_active"] and _last_super(db, tid, u, sp):
                raise LoiQT("Không khoá được Super Admin cuối cùng", 409)
            s["is_active"] = bool(data["is_active"])
    pw = data.get("password") or ""
    if pw:
        if kind != "LOCAL":
            raise LoiQT("Tài khoản AD đổi mật khẩu trong AD")
        if len(pw) < 6:
            raise LoiQT("Mật khẩu tối thiểu 6 ký tự")
        s["password_hash"] = hash_password(pw)
    repo.update_by_id(u["_id"], {"$set": s})
    if (pw or s.get("is_active") is False) and not is_self:
        revoke_user_sessions(db, tid, u["_id"])
    new = repo.find_one({"_id": u["_id"]}, {"password_hash": 0, "totp_secret_enc": 0})
    assert new is not None
    return _public(new, kind, ctx, pols, sp)


def delete_user(db: Database, ctx: Ctx, user_id: str) -> str:
    tid = ctx.tenant_id
    u, kind, repo = _find(db, tid, user_id)
    pols = _pols(db, tid)
    sp = _super_pid(pols)
    if u["_id"] == ctx.user_id:
        raise LoiQT("Không thể tự xoá tài khoản của chính mình", 403)
    _check_target(ctx, u, sp)
    if _last_super(db, tid, u, sp):
        raise LoiQT("Không xoá được Super Admin cuối cùng", 409)
    revoke_user_sessions(db, tid, u["_id"])
    repo.delete_by_id(u["_id"])
    return kind


def kind_of(db: Database, ctx: Ctx, user_id: str) -> str:
    return _find(db, ctx.tenant_id, user_id)[1]


# ====================================================================== phiên đang mở
ONLINE = timedelta(minutes=15)


def sessions(db: Database, ctx: Ctx, now: datetime | None = None) -> list[dict]:
    """Phiên còn hạn có hoạt động trong 15 phút (đệm `last_seen_at` ≤ 60 s). Super Admin chỉ hiện với Super Admin."""
    now = now or datetime.now(UTC)
    out = []
    q = {"is_active": True, "expires_at": {"$gt": now}, "last_seen_at": {"$gt": now - ONLINE}}
    for s in repo_for(db, ctx.tenant_id, "sessions").find(q).sort("last_seen_at", -1).limit(500):
        if s.get("is_super") and not ctx.is_super:
            continue
        out.append({"id": str(s["_id"]), "username": s.get("username") or "", "user_kind": s.get("user_kind") or "",
                    "method": s.get("method") or s.get("user_kind") or "", "ip": s.get("ip") or "",
                    "created_at": _iso(s.get("created_at")), "last_seen_at": _iso(s.get("last_seen_at")),
                    "is_me": s["_id"] == ctx.session_id, "is_super": bool(s.get("is_super"))})
    return out


def kick(db: Database, ctx: Ctx, session_id: str) -> None:
    sid = _oid(session_id)
    s = repo_for(db, ctx.tenant_id, "sessions").find_one({"_id": sid, "is_active": True}) if sid else None
    if s is None:
        raise LoiQT("Phiên không còn", 404)
    if s.get("is_super") and not ctx.is_super:
        raise LoiQT("Không có quyền thao tác trên phiên Super Admin", 403)
    if s["_id"] == ctx.session_id:
        raise LoiQT("Đây là phiên của chính bạn — dùng nút Đăng xuất", 409)
    revoke_session(db, ctx.tenant_id, s["_id"])


# ====================================================================== nhật ký hệ thống
def audit(db: Database, ctx: Ctx, *, system: str | None, q: str | None, since: datetime | None,
          until: datetime | None, limit: int) -> list[dict]:
    query: dict = {}
    if system:
        query["system"] = system
    if q:
        rx = {"$regex": escape(q.strip()), "$options": "i"}
        query["$or"] = [{"actor": rx}, {"action": rx}, {"detail": rx}, {"ip": rx}]
    if since or until:
        query["created_at"] = {**({"$gte": since} if since else {}), **({"$lt": until} if until else {})}
    out = []
    for d in AuditRepo(db, ctx.tenant_id).find(query).sort([("created_at", -1), ("_id", -1)]).limit(limit):
        out.append({"id": str(d["_id"]), "created_at": _iso(d.get("created_at")), "system": d.get("system") or "",
                    "actor": d.get("actor") or "", "action": d.get("action") or "", "detail": d.get("detail") or "",
                    "ip": d.get("ip") or "", "status": d.get("status")})
    return out
