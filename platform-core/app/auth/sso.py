"""Đăng nhập một lần (SSO) bằng OpenID Connect — yêu cầu thêm ở 8.3 (12/10/2026). Hệ cũ không có SSO.

Luồng (Authorization Code + PKCE, Core là "confidential client"):
1. Desktop `POST /api/auth/sso/start {tenant_code}` → Core tạo bản ghi chờ (`sso_logins`, hạn 10 phút) giữ `state`,
   `nonce`, `code_verifier`; trả `login_id` (bí mật, chỉ Desktop biết) + `auth_url`.
2. Desktop mở `auth_url` bằng TRÌNH DUYỆT của máy (người dùng đăng nhập Microsoft 365 / Google / Keycloak… kèm MFA của
   nhà cung cấp) rồi cứ 1,5 s hỏi `POST /api/auth/sso/poll {tenant_code, login_id}`.
3. Nhà cung cấp chuyển trình duyệt về `GET /api/auth/sso/callback?code&state` → Core đổi mã lấy token (kèm verifier),
   kiểm `iss` / `aud` / `exp` / `nonce` của ID token, lấy định danh (claim cấu hình được, mặc định `preferred_username`)
   rồi GHÉP với tài khoản đã đăng ký trong Core — KHÔNG tự tạo tài khoản (giống hệ cũ: AD chưa đăng ký là từ chối).
4. Lần hỏi kế tiếp nhận token phiên Core (một lần — bản ghi bị xoá ngay).

ID token nhận TRỰC TIẾP từ token endpoint qua TLS nên theo OIDC Core 3.1.3.7 (6) được dựa vào kiểm chứng TLS thay cho
chữ ký — không cần thêm thư viện JWT. `state` mang mã tổ chức (`<tenant_id>.<ngẫu nhiên>`) để callback tìm đúng tổ
chức qua TenantRepo (không truy vấn chéo tổ chức). Không cấp TOTP của Core cho SSO: MFA do nhà cung cấp lo.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from bson import ObjectId
from pymongo.database import Database

from app.audit.service import write_audit
from app.auth import methods
from app.auth.service import AuthError, ctx_json, find_ad_user, issue_session
from app.security import crypto
from app.security.tokens import hash_token, new_token
from app.tenants.repo import AdUserRepo, UserRepo, repo_for
from app.tenants.service import get_tenant_by_code

log = logging.getLogger("auth.sso")
LOGIN_TTL = timedelta(minutes=10)
_DISC_TTL = 3600.0
_DISC: dict[str, tuple[dict, float]] = {}
_CLAIMS = ("preferred_username", "upn", "email", "unique_name")


class LoiSSO(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


# ====================================================================== HTTP (test thay thế được)
def _get_json(url: str) -> dict:
    r = requests.get(url, timeout=10, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def _post_form(url: str, data: dict) -> tuple[int, dict]:
    r = requests.post(url, data=data, timeout=15, headers={"Accept": "application/json"})
    try:
        body = r.json()
    except ValueError:
        body = {"error": r.text[:300]}
    return r.status_code, body


def discovery(issuer: str, *, fresh: bool = False) -> dict:
    """Tài liệu `/.well-known/openid-configuration` của nhà cung cấp (đệm 1 giờ)."""
    iss = (issuer or "").strip().rstrip("/")
    if not iss:
        raise LoiSSO("Chưa cấu hình Issuer SSO")
    hit = _DISC.get(iss)
    if hit and hit[1] > time.monotonic() and not fresh:
        return hit[0]
    try:
        d = _get_json(f"{iss}/.well-known/openid-configuration")
    except Exception as e:
        raise LoiSSO(f"Không đọc được cấu hình OpenID của nhà cung cấp ({iss}): {type(e).__name__}") from None
    for k in ("authorization_endpoint", "token_endpoint", "issuer"):
        if not d.get(k):
            raise LoiSSO(f"Tài liệu OpenID thiếu '{k}' — Issuer có đúng không?")
    _DISC[iss] = (d, time.monotonic() + _DISC_TTL)
    return d


def test_config(cfg: dict) -> str:
    """Nút "Kiểm tra" trên trang Quản trị: đọc được tài liệu OpenID + đủ Client ID → câu báo đạt; lỗi → LoiSSO."""
    d = discovery(cfg.get("issuer") or "", fresh=True)
    if not cfg.get("client_id"):
        raise LoiSSO("Thiếu Client ID")
    return (f"Đọc được cấu hình OpenID của {d['issuer']} — trang đăng nhập {d['authorization_endpoint']}. "
            "Đăng ký Redirect URI ở nhà cung cấp rồi thử nút đăng nhập SSO trên Desktop.")


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _tenant(db: Database, tenant_code: str) -> dict:
    t = get_tenant_by_code(db, tenant_code)
    if not t:
        raise LoiSSO(AuthError("TENANT").message, 404)
    return t


# ====================================================================== 1. bắt đầu
def start(db: Database, tenant_code: str, master: str, default_redirect: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    t = _tenant(db, tenant_code)
    cfg = methods.sso_config(db, t["_id"], master)
    if not cfg["enabled"]:
        raise LoiSSO("Đăng nhập SSO đang tắt ở tổ chức này", 403)
    d = discovery(cfg["issuer"])
    login_id = new_token()
    state = f"{t['_id']}.{secrets.token_urlsafe(24)}"
    nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    redirect = cfg["redirect_uri"] or default_redirect
    repo_for(db, t["_id"], "sso_logins").insert_one({
        "state": state, "login_hash": hash_token(login_id), "nonce": nonce, "verifier": verifier,
        "redirect_uri": redirect, "status": "pending", "created_at": now, "expires_at": now + LOGIN_TTL})
    params = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": redirect,
              "scope": cfg["scopes"] or "openid profile email", "state": state, "nonce": nonce,
              "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
              "prompt": "select_account"}
    ep = d["authorization_endpoint"]
    return {"login_id": login_id, "auth_url": ep + ("&" if "?" in ep else "?") + urlencode(params),
            "expires_in": int(LOGIN_TTL.total_seconds())}


# ====================================================================== 2. nhà cung cấp gọi về
def _claims(id_token: str) -> dict:
    try:
        part = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        raise LoiSSO("ID token không đọc được") from None


def _check(claims: dict, d: dict, client_id: str, nonce: str, now: datetime) -> None:
    iss = str(d["issuer"])
    if "{tenantid}" in iss and claims.get("tid"):  # Microsoft Entra đa tổ chức ("common"/"organizations")
        iss = iss.replace("{tenantid}", str(claims["tid"]))
    if str(claims.get("iss") or "").rstrip("/") != iss.rstrip("/"):
        raise LoiSSO("ID token không do đúng nhà cung cấp cấp (iss)")
    aud = claims.get("aud")
    if client_id not in (aud if isinstance(aud, list) else [aud]):
        raise LoiSSO("ID token không cấp cho ứng dụng này (aud)")
    if float(claims.get("exp") or 0) < now.timestamp() - 60:
        raise LoiSSO("ID token đã hết hạn")
    if claims.get("nonce") != nonce:
        raise LoiSSO("ID token không khớp phiên đăng nhập (nonce)")


def identity(claims: dict, claim: str) -> str:
    for k in (claim, *_CLAIMS):
        v = claims.get(k) if k else None
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def match_user(db: Database, tid: ObjectId, ident: str) -> tuple[dict | None, str]:
    """Định danh SSO → tài khoản ĐÃ ĐĂNG KÝ: AD (tên / UPN / email) → Local (email) → AD trùng phần trước @ (duy nhất —
    UPN Microsoft 365 hay khác domain AD nội bộ: anh.nguyen@phenikaa-uni.edu.vn ↔ anh.nguyen@phenikaamec.local)."""
    lc = ident.lower()
    u = find_ad_user(db, tid, lc) or AdUserRepo(db, tid).find_one({"email_lc": lc})
    if u:
        return u, "AD"
    u = UserRepo(db, tid).find_one({"email_lc": lc})
    if u:
        return u, "LOCAL"
    local = lc.split("@", 1)[0]
    if local and "@" in lc:
        import re

        rx = {"$regex": f"^{re.escape(local)}(@|$)"}
        hits = list(AdUserRepo(db, tid).find({"username_lc": rx}).limit(2))
        if len(hits) == 1:
            return hits[0], "AD"
    return None, ""


def callback(db: Database, *, state: str, code: str, error: str, error_description: str, master: str,
             ttl_hours: int, ip: str, now: datetime | None = None) -> tuple[bool, str]:
    """Trả (thành công?, câu hiển thị trên trang trình duyệt). Không bao giờ ném lỗi ra ngoài."""
    now = now or datetime.now(UTC)
    tid_s = (state or "").split(".", 1)[0]
    try:
        tid = ObjectId(tid_s)
    except Exception:
        return False, "Liên kết đăng nhập không hợp lệ."
    repo = repo_for(db, tid, "sso_logins")
    rec = repo.find_one({"state": state, "status": "pending"})
    if rec is None or _aware(rec["expires_at"]) < now:
        return False, "Phiên đăng nhập đã hết hạn hoặc đã dùng — bấm lại nút đăng nhập SSO trên ứng dụng."

    def ket(ok: bool, msg: str, **extra: Any) -> tuple[bool, str]:
        repo.update_one({"_id": rec["_id"]}, {"$set": {"status": "done" if ok else "error", "message": msg, **extra}})
        return ok, msg

    if error:
        return ket(False, f"Nhà cung cấp SSO báo lỗi: {error_description or error}")
    try:
        tenant = db.tenants.find_one({"_id": tid, "status": "ACTIVE"})
        if not tenant:
            return ket(False, AuthError("TENANT").message)
        cfg = methods.sso_config(db, tid, master)
        if not cfg["enabled"]:
            return ket(False, "Đăng nhập SSO đang tắt ở tổ chức này.")
        d = discovery(cfg["issuer"])
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": rec["redirect_uri"],
                "client_id": cfg["client_id"], "code_verifier": rec["verifier"]}
        if cfg["client_secret"]:
            data["client_secret"] = cfg["client_secret"]
        status, body = _post_form(d["token_endpoint"], data)
        if status != 200 or not body.get("id_token"):
            why = body.get("error_description") or body.get("error") or f"HTTP {status}"
            return ket(False, f"Không đổi được mã đăng nhập: {str(why)[:300]}")
        claims = _claims(str(body["id_token"]))
        _check(claims, d, cfg["client_id"], rec["nonce"], now)
        ident = identity(claims, cfg["username_claim"])
        if not ident:
            return ket(False, "Nhà cung cấp không trả tên đăng nhập / email (kiểm scope 'profile email').")
        doms = [x.strip().lower().lstrip("@") for x in cfg["allowed_domains"].replace(";", ",").split(",") if x.strip()]
        if doms and ident.lower().rsplit("@", 1)[-1] not in doms:
            write_audit(db, tid, action="LOGIN_FAIL", actor=ident, detail="SSO_DOMAIN", ip=ip)
            return ket(False, f"Tài khoản {ident} không thuộc tên miền được phép.")
        user, kind = match_user(db, tid, ident)
        if user is None or not user.get("is_active", True):
            write_audit(db, tid, action="LOGIN_FAIL", actor=ident, detail="SSO_UNREGISTERED", ip=ip)
            return ket(False, f"Tài khoản {ident} chưa được cấp quyền dùng IT Monitor (hoặc đang bị khoá) — liên hệ "
                              "quản trị để được thêm.")
        try:
            r = issue_session(db, tenant, user, kind, ip=ip, ttl_hours=ttl_hours, now=now, method="SSO")
        except AuthError as e:
            return ket(False, e.message)
        result = {"expires_at": r.expires_at.isoformat(), "user": r.user, "session": ctx_json(r.ctx)}
        return ket(True, f"Đăng nhập thành công: {user['username']}", token_enc=crypto.encrypt(r.token, master),
                   result=result)
    except LoiSSO as e:
        return ket(False, str(e))
    except Exception:
        log.exception("SSO callback lỗi")
        return ket(False, "Lỗi khi xử lý đăng nhập SSO — xem nhật ký Core.")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ====================================================================== 3. Desktop hỏi kết quả
def poll(db: Database, tenant_code: str, login_id: str, master: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    t = _tenant(db, tenant_code)
    repo = repo_for(db, t["_id"], "sso_logins")
    rec = repo.find_one({"login_hash": hash_token(login_id or "")})
    if rec is None:
        return {"status": "expired", "message": "Phiên đăng nhập SSO không còn — bấm lại nút đăng nhập."}
    if rec["status"] == "pending":
        if _aware(rec["expires_at"]) < now:
            repo.delete_one({"_id": rec["_id"]})
            return {"status": "expired", "message": "Quá 10 phút chưa đăng nhập xong — bấm lại nút đăng nhập."}
        return {"status": "pending"}
    repo.delete_one({"_id": rec["_id"]})  # kết quả chỉ trao MỘT lần
    if rec["status"] == "error":
        return {"status": "error", "message": rec.get("message") or "Đăng nhập SSO không thành công"}
    return {"status": "done", "token": crypto.decrypt(rec["token_enc"], master), **(rec.get("result") or {})}


def page(ok: bool, msg: str) -> str:
    """Trang trình duyệt sau callback (trình duyệt hệ thống, không phải cửa sổ ứng dụng)."""
    color, title = ("#1d7438", "Đăng nhập thành công") if ok else ("#b42318", "Đăng nhập không thành công")
    tail = "Quay lại ứng dụng Phenikaa IT Monitor — có thể đóng thẻ này." if ok else \
        "Đóng thẻ này, quay lại ứng dụng và thử lại."
    return (f"<!doctype html><html lang=vi><head><meta charset=utf-8><title>{title}</title></head>"
            f"<body style='font-family:system-ui,Segoe UI,Arial;max-width:560px;margin:72px auto;padding:0 16px'>"
            f"<h2 style='color:{color}'>{title}</h2><p>{html.escape(msg)}</p><p style='color:#666'>{tail}</p>"
            f"{'<script>setTimeout(function(){window.close()},1500)</script>' if ok else ''}</body></html>")
