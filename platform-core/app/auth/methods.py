"""Cấu hình CƠ CHẾ ĐĂNG NHẬP theo tổ chức (Sổ tay 8.3 + yêu cầu thêm SSO, 12/10/2026).

Ba cơ chế:
- **Local** (tài khoản + mật khẩu lưu trong Core) — LUÔN BẬT, không có công tắc: tắt được là có thể tự khoá mình ra
  ngoài (Super Admin luôn là tài khoản Local).
- **LDAP / AD** — công tắc `ldap.enabled`. Tắt: tài khoản AD KHÔNG đăng nhập bằng mật khẩu được nữa (Core không gọi
  LDAP); tài khoản AD vẫn vào được bằng SSO nếu SSO đang bật.
- **SSO (OpenID Connect)** — công tắc `sso.enabled`. Tắt: nút SSO biến khỏi màn đăng nhập, mọi API SSO từ chối.

Lưu trong `settings` mỗi khoá một tài liệu (`ldap.server`, `sso.client_id`…) — cùng kiểu khoá `ldap.*` đăng nhập đã đọc.
Bí mật (`ldap.bind_pass_enc`, `sso.client_secret_enc`) mã hoá AES-256-GCM bằng khoá chủ; API chỉ trả mặt nạ.
Chưa từng gạt công tắc LDAP (không có `ldap.enabled`) → coi là BẬT, giữ nguyên hành vi trước khi có công tắc (thiếu địa
chỉ máy chủ thì bind vẫn thất bại như cũ). SSO mặc định TẮT.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.security import crypto
from app.tenants.repo import SettingRepo

LDAP_TEXT = ("server", "domain", "base_dn", "bind_user")
SSO_TEXT = ("provider_name", "issuer", "client_id", "scopes", "username_claim", "allowed_domains", "redirect_uri")
SSO_DEFAULTS = {"provider_name": "Microsoft 365", "scopes": "openid profile email",
                "username_claim": "preferred_username"}


class LoiCauHinh(ValueError):
    pass


def _all(db: Database, tid: ObjectId) -> dict[str, Any]:
    return {d["key"]: d.get("value") for d in SettingRepo(db, tid).find({"key": {"$regex": r"^(ldap|sso)\."}})}


def _set(db: Database, tid: ObjectId, values: dict[str, Any]) -> None:
    repo = SettingRepo(db, tid)
    for k, v in values.items():
        if v is None:
            repo.delete_one({"key": k})
        else:
            repo.update_one({"key": k}, {"$set": {"value": v, "updated_at": datetime.now(UTC)}}, upsert=True)


def _secret(raw: dict, key: str, master: str) -> str:
    enc = raw.get(key)
    if not enc:
        return ""
    try:
        return crypto.decrypt(str(enc), master)
    except Exception:
        return ""


def ldap_enabled(raw: dict) -> bool:
    v = raw.get("ldap.enabled")
    return True if v is None else bool(v)


def ldap_config(db: Database, tid: ObjectId, master: str) -> dict:
    """Cấu hình LDAP ĐẦY ĐỦ (kể cả mật khẩu bind đã giải mã) — chỉ dùng nội bộ."""
    raw = _all(db, tid)
    cfg: dict[str, Any] = {k: str(raw.get(f"ldap.{k}") or "").strip() for k in LDAP_TEXT}
    cfg["bind_pass"] = _secret(raw, "ldap.bind_pass_enc", master)
    cfg["enabled"] = ldap_enabled(raw)
    return cfg


def sso_config(db: Database, tid: ObjectId, master: str) -> dict:
    raw = _all(db, tid)
    cfg: dict[str, Any] = {k: str(raw.get(f"sso.{k}") or SSO_DEFAULTS.get(k, "")).strip() for k in SSO_TEXT}
    cfg["client_secret"] = _secret(raw, "sso.client_secret_enc", master)
    cfg["enabled"] = bool(raw.get("sso.enabled"))
    return cfg


def public(db: Database, tid: ObjectId, master: str, default_redirect: str = "") -> dict:
    ld, so = ldap_config(db, tid, master), sso_config(db, tid, master)
    ldap_out = {k: ld[k] for k in LDAP_TEXT}
    ldap_out.update(enabled=ld["enabled"], has_bind_pass=bool(ld["bind_pass"]),
                    bind_pass_mask="*" * len(ld["bind_pass"]))
    sso_out = {k: so[k] for k in SSO_TEXT}
    sso_out.update(enabled=so["enabled"], has_client_secret=bool(so["client_secret"]),
                   client_secret_mask="*" * len(so["client_secret"]),
                   effective_redirect_uri=so["redirect_uri"] or default_redirect)
    return {"local": {"enabled": True}, "ldap": ldap_out, "sso": sso_out}


def save_ldap(db: Database, tid: ObjectId, master: str, data: dict) -> None:
    vals: dict[str, Any] = {}
    for k in LDAP_TEXT:
        if data.get(k) is not None:
            vals[f"ldap.{k}"] = str(data[k]).strip()[:300]
    srv = vals.get("ldap.server")
    if srv and not srv.lower().startswith(("ldap://", "ldaps://")) and "/" in srv:
        raise LoiCauHinh("Địa chỉ LDAP dạng ldaps://<ip>:636, ldap://<ip>:389 hoặc chỉ <ip>")
    if data.get("bind_pass"):
        vals["ldap.bind_pass_enc"] = crypto.encrypt(str(data["bind_pass"]), master)
    elif data.get("clear_bind_pass"):
        vals["ldap.bind_pass_enc"] = None
    if data.get("enabled") is not None:
        enabled = bool(data["enabled"])
        server = vals.get("ldap.server", ldap_config(db, tid, master)["server"])
        if enabled and not server:
            raise LoiCauHinh("Muốn bật LDAP phải nhập địa chỉ máy chủ LDAP")
        vals["ldap.enabled"] = enabled
    _set(db, tid, vals)


def save_sso(db: Database, tid: ObjectId, master: str, data: dict) -> None:
    vals: dict[str, Any] = {}
    for k in SSO_TEXT:
        if data.get(k) is not None:
            vals[f"sso.{k}"] = str(data[k]).strip()[:500]
    iss = vals.get("sso.issuer")
    if iss and not _url_ok(iss):
        raise LoiCauHinh("Issuer phải là địa chỉ https:// (http:// chỉ cho máy thử 127.0.0.1 / localhost)")
    red = vals.get("sso.redirect_uri")
    if red and not red.startswith(("https://", "http://")):
        raise LoiCauHinh("Redirect URI phải bắt đầu bằng https://")
    if data.get("client_secret"):
        vals["sso.client_secret_enc"] = crypto.encrypt(str(data["client_secret"]), master)
    elif data.get("clear_client_secret"):
        vals["sso.client_secret_enc"] = None
    if data.get("enabled") is not None:
        enabled = bool(data["enabled"])
        cur = sso_config(db, tid, master)
        issuer = vals.get("sso.issuer", cur["issuer"])
        client = vals.get("sso.client_id", cur["client_id"])
        if enabled and not (issuer and client):
            raise LoiCauHinh("Muốn bật SSO phải nhập Issuer và Client ID")
        vals["sso.enabled"] = enabled
    _set(db, tid, vals)


def _url_ok(url: str) -> bool:
    u = url.lower()
    return u.startswith("https://") or u.startswith(("http://127.0.0.1", "http://localhost"))


def login_methods(db: Database, tid: ObjectId) -> dict:
    """Công khai cho màn đăng nhập (không cần đăng nhập): chỉ cờ bật/tắt + nhãn nút SSO."""
    raw = _all(db, tid)
    return {"local": True, "ldap": ldap_enabled(raw), "sso": bool(raw.get("sso.enabled")),
            "sso_label": str(raw.get("sso.provider_name") or SSO_DEFAULTS["provider_name"])}
