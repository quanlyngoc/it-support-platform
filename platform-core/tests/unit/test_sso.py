# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""SSO OpenID Connect (yêu cầu thêm 8.3): công tắc bật/tắt, start → callback → poll (token trao MỘT lần), PKCE + nonce,
kiểm iss/aud/exp/nonce, ghép tài khoản đã đăng ký (AD theo UPN / email / phần trước @, Local theo email), chưa đăng ký
thì từ chối, giới hạn tên miền, bí mật client chỉ trả mặt nạ, cô lập tổ chức. Nhà cung cấp giả (không gọi mạng)."""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

from app.auth import sso
from app.tenants import service as tsvc
from app.tenants.repo import UserRepo, repo_for
from tests.conftest import auth, login

ISS = "https://idp.test/tenant-1/v2.0"


def _jwt(claims: dict) -> str:
    def b(x: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(x).encode()).rstrip(b"=").decode()

    return f"{b({'alg': 'RS256'})}.{b(claims)}.chu-ky"


class FakeIdP:
    def __init__(self):
        self.ident = "nv.ad@phenikaamec.local"
        self.claims: dict = {}
        self.posted: list[dict] = []
        self.db = None

    def get_json(self, url: str) -> dict:
        assert url == f"{ISS}/.well-known/openid-configuration"
        return {
            "issuer": ISS,
            "authorization_endpoint": "https://idp.test/authorize",
            "token_endpoint": "https://idp.test/token",
        }

    def post_form(self, url: str, data: dict):
        self.posted.append(data)
        if data["code"] == "ma-hong":
            return 400, {"error": "invalid_grant", "error_description": "Mã đã dùng"}
        rec = self.db["sso_logins"].find_one({"verifier": data["code_verifier"]})  # PKCE: đúng verifier của phiên
        claims = {
            "iss": ISS,
            "aud": "cid",
            "exp": time.time() + 600,
            "nonce": rec["nonce"] if rec else "?",
            "preferred_username": self.ident,
            **self.claims,
        }
        return 200, {"id_token": _jwt(claims), "access_token": "x"}


@pytest.fixture
def idp(monkeypatch, db):
    f = FakeIdP()
    f.db = db
    sso._DISC.clear()
    monkeypatch.setattr(sso, "_get_json", f.get_json)
    monkeypatch.setattr(sso, "_post_form", f.post_form)
    return f


def _bat_sso(client, h, **kw):
    body = {
        "enabled": True,
        "issuer": ISS,
        "client_id": "cid",
        "client_secret": "bi-mat-client",
        "provider_name": "Microsoft 365",
        **kw,
    }
    r = client.put("/api/admin/auth-config/sso", headers=h, json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["sso"]


def _start(client, tenant="AAA"):
    r = client.post("/api/auth/sso/start", json={"tenant_code": tenant})
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    q = parse_qs(urlparse(j["auth_url"]).query)
    return j["login_id"], q


def _cb(client, state, code="ma-dung"):
    return client.get(f"/api/auth/sso/callback?code={code}&state={state}")


def test_sso_tron_luong(client, two_tenants, db, idp):
    A = two_tenants["A"]
    h = auth(login(client, "AAA", "admin", "Admin@123")[1]["token"])
    ad = tsvc.create_user(
        db,
        A["tenant"]["_id"],
        "nv.ad@phenikaamec.local",
        user_type="AD",
        policy_ids=[A["view_pid"]],
        upn="nv.ad@phenikaamec.local",
    )
    # tắt (mặc định): không có nút, không bắt đầu được
    assert client.get("/api/auth/methods?tenant_code=AAA").get_json()["sso"] is False
    assert client.post("/api/auth/sso/start", json={"tenant_code": "AAA"}).status_code == 403
    assert (
        client.put("/api/admin/auth-config/sso", headers=h, json={"enabled": True}).status_code == 400
    )  # thiếu issuer
    assert client.put("/api/admin/auth-config/sso", headers=h, json={"issuer": "http://idp.ngoai"}).status_code == 400
    so = _bat_sso(client, h)
    assert so["has_client_secret"] and so["client_secret_mask"] == "*" * 13 and "client_secret" not in so
    assert client.get("/api/auth/methods?tenant_code=AAA").get_json() == {
        "local": True,
        "ldap": True,
        "sso": True,
        "sso_label": "Microsoft 365",
    }
    t = client.post("/api/admin/auth-config/sso/test", headers=h, json={}).get_json()
    assert t["ok"] and "idp.test/authorize" in t["message"]

    login_id, q = _start(client)
    assert q["client_id"] == ["cid"] and q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"]
    assert q["redirect_uri"][0].endswith("/api/auth/sso/callback") and q["state"][0].startswith(str(A["tenant"]["_id"]))
    assert client.post("/api/auth/sso/poll", json={"tenant_code": "AAA", "login_id": login_id}).get_json() == {
        "status": "pending"
    }
    r = _cb(client, q["state"][0])
    assert r.status_code == 200 and "Đăng nhập thành công" in r.get_data(as_text=True)
    assert idp.posted[-1]["client_secret"] == "bi-mat-client" and idp.posted[-1]["redirect_uri"] == q["redirect_uri"][0]
    j = client.post("/api/auth/sso/poll", json={"tenant_code": "AAA", "login_id": login_id}).get_json()
    assert (
        j["status"] == "done" and j["user"]["username"] == "nv.ad@phenikaamec.local" and j["user"]["user_type"] == "AD"
    )
    me = client.get("/api/auth/me", headers=auth(j["token"])).get_json()
    assert me["username"] == "nv.ad@phenikaamec.local" and me["permissions"] == ["user.view"]
    # token trao MỘT lần; callback dùng lại → từ chối
    assert (
        client.post("/api/auth/sso/poll", json={"tenant_code": "AAA", "login_id": login_id}).get_json()["status"]
        == "expired"
    )
    assert _cb(client, q["state"][0]).status_code == 400
    sess = [
        s for s in client.get("/api/admin/sessions", headers=h).get_json()["items"] if s["username"] == ad["username"]
    ]
    assert sess[0]["method"] == "SSO"
    # LDAP TẮT không chặn SSO
    client.put("/api/admin/auth-config/ldap", headers=h, json={"enabled": False, "server": "ldap://1.2.3.4"})
    login_id, q = _start(client)
    assert _cb(client, q["state"][0]).status_code == 200


def test_sso_ghep_va_tu_choi(client, two_tenants, db, idp):
    A = two_tenants["A"]
    tid = A["tenant"]["_id"]
    h = auth(login(client, "AAA", "admin", "Admin@123")[1]["token"])
    _bat_sso(client, h)
    tsvc.create_user(db, tid, "anh.nguyen@phenikaamec.local", user_type="AD", policy_ids=[A["view_pid"]])
    UserRepo(db, tid).update_one({"username_lc": "gv01"}, {"$set": {"email": "GV01@uni.vn", "email_lc": "gv01@uni.vn"}})

    def chay(ident: str, **claims):
        idp.ident, idp.claims = ident, claims
        lid, q = _start(client)
        r = _cb(client, q["state"][0])
        return r.status_code, client.post("/api/auth/sso/poll", json={"tenant_code": "AAA", "login_id": lid}).get_json()

    code, j = chay("anh.nguyen@phenikaa-uni.edu.vn")  # UPN Microsoft 365 khác domain AD → khớp phần trước @
    assert code == 200 and j["user"]["username"] == "anh.nguyen@phenikaamec.local"
    code, j = chay("gv01@uni.vn")  # Local khớp email
    assert code == 200 and j["user"]["username"] == "gv01" and j["user"]["user_type"] == "LOCAL"
    code, j = chay("la.mat@uni.vn")
    assert code == 400 and j["status"] == "error" and "chưa được cấp quyền" in j["message"]
    code, j = chay("gv01@uni.vn", nonce="khac")
    assert code == 400 and "nonce" in j["message"]
    code, j = chay("gv01@uni.vn", aud="ung-dung-khac")
    assert code == 400 and "aud" in j["message"]
    code, j = chay("gv01@uni.vn", iss="https://gia-mao.test")
    assert code == 400 and "iss" in j["message"]
    code, j = chay("gv01@uni.vn", exp=time.time() - 3600)
    assert code == 400 and "hết hạn" in j["message"]
    # tài khoản bị khoá
    UserRepo(db, tid).update_one({"username_lc": "gv01"}, {"$set": {"is_active": False}})
    assert chay("gv01@uni.vn")[0] == 400
    # giới hạn tên miền
    _bat_sso(client, h, allowed_domains="phenikaa-uni.edu.vn")
    code, j = chay("anh.nguyen@gmail.com")
    assert code == 400 and "tên miền" in j["message"]
    assert chay("anh.nguyen@phenikaa-uni.edu.vn")[0] == 200
    # nhà cung cấp báo lỗi / mã hỏng / state lạ
    lid, q = _start(client)
    r = client.get(f"/api/auth/sso/callback?error=access_denied&error_description=Người dùng huỷ&state={q['state'][0]}")
    assert r.status_code == 400 and "Người dùng huỷ" in r.get_data(as_text=True)
    assert (
        client.post("/api/auth/sso/poll", json={"tenant_code": "AAA", "login_id": lid}).get_json()["status"] == "error"
    )
    lid, q = _start(client)
    assert "Mã đã dùng" in _cb(client, q["state"][0], code="ma-hong").get_data(as_text=True)
    assert client.get("/api/auth/sso/callback?code=x&state=rac").status_code == 400
    # hết hạn 10 phút
    lid, q = _start(client)
    repo_for(db, tid, "sso_logins").update_one(
        {"state": q["state"][0]}, {"$set": {"expires_at": sso.datetime(2000, 1, 1, tzinfo=sso.UTC)}}
    )
    assert (
        client.post("/api/auth/sso/poll", json={"tenant_code": "AAA", "login_id": lid}).get_json()["status"]
        == "expired"
    )
    # tổ chức khác: SSO của AAA không áp, login_id của AAA không hỏi được ở BBB
    assert client.post("/api/auth/sso/start", json={"tenant_code": "BBB"}).status_code == 403
    lid, q = _start(client)
    assert (
        client.post("/api/auth/sso/poll", json={"tenant_code": "BBB", "login_id": lid}).get_json()["status"]
        == "expired"
    )
    # tắt SSO giữa chừng → callback từ chối
    client.put("/api/admin/auth-config/sso", headers=h, json={"enabled": False})
    assert _cb(client, q["state"][0]).status_code == 400
    assert client.get("/api/auth/methods?tenant_code=AAA").get_json()["sso"] is False
