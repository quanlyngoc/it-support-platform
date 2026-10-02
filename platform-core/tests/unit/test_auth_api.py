"""API xác thực + phân quyền + nhật ký (đặc tả §10, §50, 4A.5–4A.9; luật cũ mục 8.4–8.5)."""
from __future__ import annotations

import pyotp

from app.auth import service as asvc
from app.security import crypto
from app.tenants import service as tsvc
from app.tenants.repo import AuditRepo, UserRepo
from tests.conftest import AD_PASSWORD, TEST_SETTINGS, auth, login


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_dang_nhap_dung_tra_token_va_quyen(client, two_tenants):
    code, j = login(client, "aaa", "ADMIN", "Admin@123")  # mã tổ chức + tên không phân biệt hoa thường
    assert code == 200 and j["token"]
    assert j["session"]["tenant_code"] == "AAA" and j["session"]["is_super"] is True
    me = client.get("/api/auth/me", headers=auth(j["token"]))
    assert me.status_code == 200 and me.get_json()["username"] == "admin"


def test_sai_mat_khau_sai_to_chuc_tai_khoan_khong_ton_tai(client, two_tenants, db):
    assert login(client, "AAA", "admin", "sai")[1]["code"] == "CREDENTIALS"
    assert login(client, "AAA", "khong-co", "x")[1]["code"] == "CREDENTIALS"
    code, j = login(client, "ZZZ", "admin", "Admin@123")
    assert code == 401 and j["code"] == "TENANT"
    tid = two_tenants["A"]["tenant"]["_id"]
    assert AuditRepo(db, tid).count({"action": "LOGIN_FAIL"}) == 2


def test_khong_co_token_hoac_token_rac(client, two_tenants):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=auth("rac")).status_code == 401


def test_token_to_chuc_A_khong_dung_duoc_cho_B(client, two_tenants):
    _, ja = login(client, "AAA", "gv01", "Gv@12345")
    me = client.get("/api/auth/me", headers=auth(ja["token"])).get_json()
    assert me["tenant_code"] == "AAA"  # tổ chức lấy từ phiên, không có cách nào "chọn" B
    r = client.get("/api/auth/me", headers={**auth(ja["token"]), "X-Tenant-Code": "BBB"})
    assert r.get_json()["tenant_code"] == "AAA"


def test_mot_thiet_bi_mot_thoi_diem(client, two_tenants):
    _, j1 = login(client, "AAA", "gv01", "Gv@12345")
    assert client.get("/api/auth/me", headers=auth(j1["token"])).status_code == 200
    _, j2 = login(client, "AAA", "gv01", "Gv@12345")
    asvc.clear_cache()  # bỏ đệm 15 giây để thấy ngay hiệu lực
    assert client.get("/api/auth/me", headers=auth(j1["token"])).status_code == 401
    assert client.get("/api/auth/me", headers=auth(j2["token"])).status_code == 200


def test_super_admin_dang_nhap_nhieu_noi(client, two_tenants):
    _, j1 = login(client, "AAA", "admin", "Admin@123")
    _, j2 = login(client, "AAA", "admin", "Admin@123")
    asvc.clear_cache()
    assert client.get("/api/auth/me", headers=auth(j1["token"])).status_code == 200
    assert client.get("/api/auth/me", headers=auth(j2["token"])).status_code == 200


def test_gioi_han_ip_theo_tai_khoan(client, two_tenants, db):
    tid = two_tenants["A"]["tenant"]["_id"]
    UserRepo(db, tid).update_one({"username_lc": "gv01"}, {"$set": {"allowed_ip_cidrs": ["10.6.44.0/24"]}})
    # Kết nối thẳng (không qua proxy tin cậy) -> X-Forwarded-For bị bỏ qua
    code, j = login(client, "AAA", "gv01", "Gv@12345", ip="10.9.9.9", xff="10.6.44.7")
    assert code == 401 and j["code"] == "IP"
    # Qua Caddy (127.0.0.1) -> tin X-Forwarded-For
    assert login(client, "AAA", "gv01", "Gv@12345", ip="127.0.0.1", xff="10.6.44.7")[0] == 200
    assert login(client, "AAA", "gv01", "Gv@12345", ip="127.0.0.1", xff="10.6.99.7")[0] == 401
    # Super Admin miễn trừ
    UserRepo(db, tid).update_one({"username_lc": "admin"}, {"$set": {"allowed_ip_cidrs": ["10.6.44.0/24"]}})
    assert login(client, "AAA", "admin", "Admin@123", ip="10.9.9.9")[0] == 200


def test_totp(client, two_tenants, db):
    tid = two_tenants["A"]["tenant"]["_id"]
    secret = pyotp.random_base32()
    UserRepo(db, tid).update_one({"username_lc": "gv01"}, {"$set": {
        "totp_enabled": True, "totp_secret_enc": crypto.encrypt(secret, TEST_SETTINGS.MASTER_KEY_B64)}})
    assert login(client, "AAA", "gv01", "Gv@12345")[1]["code"] == "TOTP_REQUIRED"
    assert login(client, "AAA", "gv01", "Gv@12345", totp="000000")[1]["code"] == "TOTP"
    assert login(client, "AAA", "gv01", "Gv@12345", totp=pyotp.TOTP(secret).now())[0] == 200
    # sai mật khẩu thì không được biết tài khoản có bật TOTP hay không
    assert login(client, "AAA", "gv01", "sai")[1]["code"] == "CREDENTIALS"


def test_tai_khoan_ad(client, two_tenants, db):
    tid = two_tenants["A"]["tenant"]["_id"]
    tsvc.create_user(db, tid, "nv.ad", user_type="AD", policy_ids=[two_tenants["A"]["view_pid"]])
    code, j = login(client, "AAA", "nv.ad", AD_PASSWORD)
    assert code == 200 and j["user"]["user_type"] == "AD" and j["session"]["permissions"] == ["user.view"]
    assert login(client, "AAA", "nv.ad", "sai")[0] == 401
    assert client.get("/api/auth/me", headers=auth(j["token"])).status_code == 200


def test_dang_xuat(client, two_tenants):
    _, j = login(client, "AAA", "gv01", "Gv@12345")
    assert client.post("/api/auth/logout", headers=auth(j["token"])).status_code == 200
    assert client.get("/api/auth/me", headers=auth(j["token"])).status_code == 401


def test_khoa_tai_khoan_va_treo_to_chuc_co_hieu_luc(client, two_tenants, db):
    tid = two_tenants["A"]["tenant"]["_id"]
    _, j = login(client, "AAA", "gv01", "Gv@12345")
    UserRepo(db, tid).update_one({"username_lc": "gv01"}, {"$set": {"is_active": False}})
    asvc.clear_cache()
    assert client.get("/api/auth/me", headers=auth(j["token"])).status_code == 401
    assert login(client, "AAA", "gv01", "Gv@12345")[0] == 401

    _, ja = login(client, "AAA", "admin", "Admin@123")
    db.tenants.update_one({"_id": tid}, {"$set": {"status": "SUSPENDED"}})
    asvc.clear_cache()
    assert client.get("/api/auth/me", headers=auth(ja["token"])).status_code == 401
    assert login(client, "AAA", "admin", "Admin@123")[1]["code"] == "TENANT"


def test_phan_quyen_va_nhat_ky(client, two_tenants, db):
    tid = two_tenants["A"]["tenant"]["_id"]
    _, jg = login(client, "AAA", "gv01", "Gv@12345")
    r = client.post("/api/test/control", headers=auth(jg["token"]))
    assert r.status_code == 403 and r.get_json()["code"] == "FORBIDDEN"
    _, ja = login(client, "AAA", "admin", "Admin@123")
    assert client.post("/api/test/control", headers=auth(ja["token"])).status_code == 200
    rows = list(AuditRepo(db, tid).find({"action": "POST /api/test/control"}))
    assert sorted(r["status"] for r in rows) == [200, 403]
    assert {r["actor"] for r in rows} == {"admin", "gv01"}
    # nhật ký chỉ nằm trong tổ chức A
    assert AuditRepo(db, two_tenants["B"]["tenant"]["_id"]).count({"action": "POST /api/test/control"}) == 0


def test_mat_khau_khong_bao_gio_tra_ve(client, two_tenants):
    _, j = login(client, "AAA", "admin", "Admin@123")
    text = str(j)
    assert "argon2" not in text and "password" not in text
