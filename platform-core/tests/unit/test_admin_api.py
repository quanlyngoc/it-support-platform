# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Quản trị nền tảng (Sổ tay 8.3): người dùng Local/AD, policy, phiên đang mở, nhật ký, cấu hình đăng nhập (công tắc
LDAP + nút thử), đổi mật khẩu. Luật hệ cũ: không tự khoá/xoá/đổi policy mình; người không phải Super Admin không thấy /
gán / đụng Super Admin; policy hệ thống chỉ xem; policy đang gán không xoá được."""

from __future__ import annotations

from app.auth import ldap as ldap_mod
from app.auth import service as asvc
from app.rbac.service import create_policy
from app.tenants import service as tsvc
from app.tenants.repo import SettingRepo
from tests.conftest import AD_PASSWORD, auth, login


def tok(client, user="admin", pw="Admin@123", tenant="AAA") -> str:
    code, j = login(client, tenant, user, pw)
    assert code == 200, j
    return j["token"]


def _quan_tri_vien(db, tid):
    """Tài khoản quản trị KHÔNG phải Super Admin, có đủ quyền người dùng + policy."""
    pid = create_policy(
        db,
        tid,
        "Quản trị người dùng",
        permission_codes=[
            "user.view",
            "user.edit",
            "user.toggle",
            "user.delete",
            "local_user.create",
            "ad_user.add",
            "policy.create",
            "policy.edit",
            "audit.view",
            "system.configure",
        ],
    )["_id"]
    tsvc.create_user(db, tid, "qtv", password="Qtv@1234", policy_ids=[pid])
    return pid


def test_nguoi_dung_local_va_ad(client, two_tenants, db):
    A = two_tenants["A"]
    t = tok(client)
    h = auth(t)
    view = str(A["view_pid"])
    r = client.post(
        "/api/admin/users",
        headers=h,
        json={
            "username": "it01",
            "password": "It@12345",
            "display_name": "IT 01",
            "email": "IT01@x.vn",
            "policy_ids": [view],
        },
    )
    assert r.status_code == 201, r.get_json()
    it01 = r.get_json()
    assert it01["user_type"] == "LOCAL" and it01["policies"] == ["Chi xem"] and "password_hash" not in it01
    assert (
        client.post("/api/admin/users", headers=h, json={"username": "it01", "password": "It@12345"}).status_code == 409
    )
    assert client.post("/api/admin/users", headers=h, json={"username": "it02", "password": "123"}).status_code == 400
    assert (
        client.post("/api/admin/users", headers=h, json={"username": "có dấu", "password": "123456"}).status_code == 400
    )
    # AD: gõ tên ngắn → tự ghép @domain của LDAP; bắt buộc có policy
    SettingRepo(db, A["tenant"]["_id"]).update_one(
        {"key": "ldap.domain"}, {"$set": {"value": "phenikaamec.local"}}, upsert=True
    )
    assert client.post("/api/admin/users", headers=h, json={"user_type": "AD", "username": "nv.ad"}).status_code == 400
    r = client.post("/api/admin/users", headers=h, json={"user_type": "AD", "username": "nv.ad", "policy_ids": [view]})
    assert r.status_code == 201 and r.get_json()["username"] == "nv.ad@phenikaamec.local"
    # AD đăng nhập bằng tên ngắn (khớp tên đầy đủ đã đăng ký) khi LDAP bật
    assert login(client, "AAA", "nv.ad", AD_PASSWORD)[0] == 200
    j = client.get("/api/admin/users", headers=h).get_json()
    assert {u["username"] for u in j["items"]} >= {"admin", "gv01", "it01", "nv.ad@phenikaamec.local"}
    me = next(u for u in j["items"] if u["username"] == "admin")
    assert me["is_self"] and me["is_super"] and me["policies"] == ["Super Admin"]

    # sửa: email / policy; đặt lại mật khẩu → phiên đang mở của người đó bị đăng xuất ngay
    t_it = tok(client, "it01", "It@12345")
    r = client.put(
        f"/api/admin/users/{it01['id']}",
        headers=h,
        json={"display_name": "IT Một", "password": "Moi@12345", "policy_ids": []},
    )
    assert r.status_code == 200 and r.get_json()["display_name"] == "IT Một" and r.get_json()["policies"] == []
    assert client.get("/api/auth/me", headers=auth(t_it)).status_code == 401
    assert login(client, "AAA", "it01", "Moi@12345")[0] == 200
    # khoá: có hiệu lực ngay
    t_it = tok(client, "it01", "Moi@12345")
    assert client.post(f"/api/admin/users/{it01['id']}/active", headers=h, json={"is_active": False}).status_code == 200
    assert client.get("/api/auth/me", headers=auth(t_it)).status_code == 401
    assert login(client, "AAA", "it01", "Moi@12345")[0] == 401
    # không tự khoá / tự xoá / tự đổi policy của chính mình
    my = str(A["admin"]["_id"])
    assert client.post(f"/api/admin/users/{my}/active", headers=h, json={"is_active": False}).status_code == 403
    assert client.delete(f"/api/admin/users/{my}", headers=h).status_code == 403
    r = client.put(f"/api/admin/users/{my}", headers=h, json={"policy_ids": [view], "is_active": False})
    assert r.status_code == 200 and r.get_json()["is_super"] and r.get_json()["is_active"]  # giữ nguyên
    # xoá
    assert client.delete(f"/api/admin/users/{it01['id']}", headers=h).status_code == 200
    assert client.delete(f"/api/admin/users/{it01['id']}", headers=h).status_code == 404
    # tổ chức khác không thấy
    assert all(
        u["username"] != "nv.ad@phenikaamec.local"
        for u in client.get("/api/admin/users", headers=auth(tok(client, tenant="BBB"))).get_json()["items"]
    )
    # quyền: gv01 chỉ có user.view
    hg = auth(tok(client, "gv01", "Gv@12345"))
    assert client.get("/api/admin/users", headers=hg).status_code == 200
    assert client.post("/api/admin/users", headers=hg, json={"username": "x", "password": "123456"}).status_code == 403
    assert client.get("/api/admin/audit", headers=hg).status_code == 403
    assert client.get("/api/admin/auth-config", headers=hg).status_code == 403


def test_khong_phai_super_admin(client, two_tenants, db):
    A = two_tenants["A"]
    _quan_tri_vien(db, A["tenant"]["_id"])
    hq = auth(tok(client, "qtv", "Qtv@1234"))
    j = client.get("/api/admin/users", headers=hq).get_json()
    adm = next(u for u in j["items"] if u["username"] == "admin")
    assert adm["locked"] and adm["policies"] == ["Quản trị viên"] and adm["policy_ids"] == []
    assert all(p["name"] != "Super Admin" for p in client.get("/api/admin/policies", headers=hq).get_json()["items"])
    sid = str(A["admin"]["_id"])
    assert client.put(f"/api/admin/users/{sid}", headers=hq, json={"display_name": "x"}).status_code == 403
    assert client.post(f"/api/admin/users/{sid}/active", headers=hq, json={"is_active": False}).status_code == 403
    assert client.delete(f"/api/admin/users/{sid}", headers=hq).status_code == 403
    r = client.post(
        "/api/admin/users",
        headers=hq,
        json={"username": "len", "password": "123456", "policy_ids": [str(A["super_pid"])]},
    )
    assert r.status_code == 403  # không tự tạo Super Admin
    # phiên Super Admin ẩn với người không phải Super Admin, không đá được
    tok(client)
    assert all(not s["is_super"] for s in client.get("/api/admin/sessions", headers=hq).get_json()["items"])


def test_policy(client, two_tenants, db):
    A = two_tenants["A"]
    h = auth(tok(client))
    perms = client.get("/api/admin/permissions", headers=h).get_json()["items"]
    assert {
        "code": "incident.handle",
        "name": perms[[p["code"] for p in perms].index("incident.handle")]["name"],
        "group": "Sự cố & báo cáo",
    } in perms
    from app.tenants.repo import repo_for

    rid = str(repo_for(db, A["tenant"]["_id"], "rooms").insert_one({"name": "Phòng 301 - A6"}).inserted_id)
    r = client.post(
        "/api/admin/policies",
        headers=h,
        json={"name": "Giám thị 301", "permissions": ["device.control"], "room_ids": [rid]},
    )
    assert r.status_code == 201
    pid = r.get_json()["id"]
    assert client.post("/api/admin/policies", headers=h, json={"name": "Giám thị 301"}).status_code == 409
    assert (
        client.post("/api/admin/policies", headers=h, json={"name": "X", "permissions": ["khong.co"]}).status_code
        == 400
    )
    assert client.post("/api/admin/policies", headers=h, json={"name": "Super Admin"}).status_code == 400
    items = {p["name"]: p for p in client.get("/api/admin/policies", headers=h).get_json()["items"]}
    assert items["Giám thị 301"]["rooms"] == ["Phòng 301 - A6"] and items["Giám thị 301"]["permissions"] == [
        "device.control"
    ]
    assert items["Super Admin"]["system"] and items["Super Admin"]["users"] == 1
    sp = items["Super Admin"]["id"]
    assert client.put(f"/api/admin/policies/{sp}", headers=h, json={"name": "Đổi"}).status_code == 403
    assert client.delete(f"/api/admin/policies/{sp}", headers=h).status_code == 403
    r = client.put(
        f"/api/admin/policies/{pid}",
        headers=h,
        json={"name": "Giám thị 301", "permissions": ["device.control", "incident.handle"], "room_ids": [rid]},
    )
    assert r.status_code == 200
    client.post("/api/admin/users", headers=h, json={"username": "gs301", "password": "Gs@12345", "policy_ids": [pid]})
    assert client.delete(f"/api/admin/policies/{pid}", headers=h).status_code == 409  # đang gán
    _, j = login(client, "AAA", "gs301", "Gs@12345")
    assert j["session"]["permissions"] == ["device.control", "incident.handle"] and j["session"]["room_ids"] == [rid]
    vp = str(A["view_pid"])
    assert client.delete(f"/api/admin/policies/{vp}", headers=h).status_code == 409


def test_phien_nhat_ky_doi_mat_khau(client, two_tenants, db):
    h = auth(tok(client))
    t_gv = tok(client, "gv01", "Gv@12345")
    items = client.get("/api/admin/sessions", headers=h).get_json()["items"]
    gv = next(s for s in items if s["username"] == "gv01")
    mine = next(s for s in items if s["is_me"])
    assert gv["method"] == "LOCAL" and gv["ip"]
    assert client.delete(f"/api/admin/sessions/{mine['id']}", headers=h).status_code == 409
    assert client.delete(f"/api/admin/sessions/{gv['id']}", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=auth(t_gv)).status_code == 401  # đá ngay, không chờ đệm 15 s
    # đổi mật khẩu
    hg = auth(tok(client, "gv01", "Gv@12345"))
    assert (
        client.post(
            "/api/auth/password", headers=hg, json={"old_password": "sai", "new_password": "Moi@1234"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/password", headers=hg, json={"old_password": "Gv@12345", "new_password": "123"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/password", headers=hg, json={"old_password": "Gv@12345", "new_password": "Moi@1234"}
        ).status_code
        == 200
    )
    assert login(client, "AAA", "gv01", "Moi@1234")[0] == 200
    # nhật ký: lọc từ khoá + hệ
    j = client.get("/api/admin/audit?q=PASSWORD_CHANGE", headers=h).get_json()
    assert j["total"] == 2 and {i["actor"] for i in j["items"]} == {"gv01"}  # 1 lần sai + 1 lần đổi
    assert client.get("/api/admin/audit?system=HSK", headers=h).get_json()["total"] == 0
    assert client.get("/api/admin/audit?q=LOGIN_FAIL", headers=h).get_json()["total"] == 0
    assert client.get("/api/admin/audit?system=LAB&limit=5", headers=h).get_json()["total"] == 5


def test_cong_tac_ldap_va_nut_thu(client, two_tenants, db, monkeypatch):
    A = two_tenants["A"]
    h = auth(tok(client))
    tsvc.create_user(db, A["tenant"]["_id"], "nv.ad", user_type="AD", policy_ids=[A["view_pid"]])
    j = client.get("/api/admin/auth-config", headers=h).get_json()
    assert j["local"]["enabled"] and j["ldap"]["enabled"] and not j["sso"]["enabled"]  # chưa gạt: LDAP như cũ (bật)
    assert j["sso"]["effective_redirect_uri"].endswith("/api/auth/sso/callback")
    assert (
        client.put("/api/admin/auth-config/ldap", headers=h, json={"enabled": True}).status_code == 400
    )  # thiếu máy chủ
    r = client.put(
        "/api/admin/auth-config/ldap",
        headers=h,
        json={
            "enabled": True,
            "server": "ldaps://10.0.0.5:636",
            "domain": "phenikaamec.local",
            "bind_user": "svc@x",
            "bind_pass": "BiMat@1",
        },
    )
    assert r.status_code == 200
    ld = r.get_json()["ldap"]
    assert ld["has_bind_pass"] and ld["bind_pass_mask"] == "*******" and "bind_pass" not in ld
    raw = {d["key"]: d["value"] for d in SettingRepo(db, A["tenant"]["_id"]).find({})}
    assert "BiMat@1" not in str(raw) and str(raw["ldap.bind_pass_enc"]).startswith("v1:")
    assert login(client, "AAA", "nv.ad", AD_PASSWORD)[0] == 200
    # GẠT TẮT LDAP → AD không đăng nhập bằng mật khẩu nữa; Local vẫn bình thường
    assert (
        client.put("/api/admin/auth-config/ldap", headers=h, json={"enabled": False}).get_json()["ldap"]["enabled"]
        is False
    )
    code, j = login(client, "AAA", "nv.ad", AD_PASSWORD)
    assert code == 401 and j["code"] == "LDAP_OFF"
    assert login(client, "AAA", "gv01", "Gv@12345")[0] == 200
    assert client.get("/api/auth/methods?tenant_code=AAA").get_json() == {
        "local": True,
        "ldap": False,
        "sso": False,
        "sso_label": "Microsoft 365",
    }
    assert client.get("/api/auth/methods?tenant_code=KHONG").get_json()["ldap"] is False
    client.put("/api/admin/auth-config/ldap", headers=h, json={"enabled": True})
    assert login(client, "AAA", "nv.ad", AD_PASSWORD)[0] == 200
    # nút thử: dùng giá trị đang gõ, thiếu thì giá trị đã lưu (mật khẩu bind đã lưu)
    seen = []
    that = ldap_mod.test_bind
    monkeypatch.setattr(ldap_mod, "test_bind", lambda srv, u, p: (seen.append((srv, u, p)), (True, "ok"))[1])
    r = client.post("/api/admin/auth-config/ldap/test", headers=h, json={"server": "ldap://10.0.0.6"}).get_json()
    assert r == {"ok": True, "message": "ok"} and seen[-1] == ("ldap://10.0.0.6", "svc@x", "BiMat@1")
    client.post("/api/admin/auth-config/ldap/test", headers=h, json={"test_user": "anh", "test_password": "p"})
    assert seen[-1] == ("ldaps://10.0.0.5:636", "anh@phenikaamec.local", "p")
    # bảng chẩn đoán mã lỗi AD
    assert ldap_mod.diag(result={"message": "80090308: LdapErr: DSID-0C09044E, data 775, v4563"}).startswith(
        "[data 775]"
    )
    assert ldap_mod.diag(exc_text="[WinError 10061] refused").startswith("[REFUSED]")
    assert that("", "a", "b") == (False, "Thiếu địa chỉ máy chủ LDAP.")
    asvc.clear_cache()
