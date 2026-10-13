# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Sổ tay 8.1: chat theo phòng — phía admin / phía phòng, chưa đọc THEO TỪNG NGƯỜI, LAB và HSK cùng phòng không lẫn,
ảnh dán lưu kho chung, cảm xúc mỗi người một, xoá (kèm ảnh), realtime chỉ tới đúng người."""
from __future__ import annotations

import base64

from bson import ObjectId

from app.legacy_adapter import contract as k
from app.rbac.service import create_policy
from app.realtime.hub import DESKTOP_NS
from app.tenants import service as tsvc
from app.tenants.repo import repo_for
from tests.conftest import auth
from tests.unit.conftest import tok
from tests.unit.test_power_api import _dung

JPG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0 anh thu \xff\xd9").decode()


def _nguoi(world, db, rooms):
    """gs301 / gs405 = tài khoản phòng; it02 = admin thứ hai (Super Admin)."""
    out = {}
    for user, room in (("gs301", "Phòng 301 - A6"), ("gs405", "Phòng 405 - A6")):
        pid = create_policy(db, world["tid"], f"GS {room}", permission_codes=["device.control"],
                            room_ids=[ObjectId(rooms[room])])["_id"]
        tsvc.create_user(db, world["tid"], user, password="Gs@12345", policy_ids=[pid])
        out[user] = tok(world, user=user, pw="Gs@12345")
    tsvc.create_user(db, world["tid"], "it02", password="It@12345", policy_ids=[world["t"]["P"]["super_pid"]])
    out["it02"] = tok(world, user="it02", pw="It@12345")
    out["admin"] = tok(world)
    return out


def _conv(c, t, scope="LAB"):
    items = c.get(f"/api/chat/conversations?scope={scope}", headers=auth(t)).get_json()["items"]
    return {x["room_name"]: x for x in items}


def test_chua_doc_theo_tung_nguoi_va_pham_vi(world, db):
    _, _, rooms = _dung(world)
    c, n = world["c"], _nguoi(world, db, rooms)
    r301, r405 = rooms["Phòng 301 - A6"], rooms["Phòng 405 - A6"]
    assert c.get("/api/chat/me", headers=auth(n["gs301"])).get_json() == {
        "side": "room", "name": "gs301", "rooms": [{"id": r301, "name": "Phòng 301 - A6"}]}
    assert c.get("/api/chat/me", headers=auth(n["admin"])).get_json()["side"] == "admin"
    assert list(_conv(c, n["gs301"])) == ["Phòng 301 - A6"]  # phía phòng luôn thấy phòng mình (kể cả chưa có tin)
    assert _conv(c, n["admin"]) == {}  # admin: chỉ phòng đã có tin
    m = c.post("/api/chat/send", json={"room_id": r301, "message": "Máy 05 không vào được mạng"},
               headers=auth(n["gs301"])).get_json()
    assert m["is_admin"] is False and m["sender"] == "gs301"
    assert c.post("/api/chat/send", json={"room_id": r405, "message": "x"}, headers=auth(n["gs301"])).status_code == 404
    for who in ("admin", "it02"):
        x = _conv(c, n[who])["Phòng 301 - A6"]
        assert (x["unread"], x["last"], x["last_admin"]) == (1, "Máy 05 không vào được mạng", False)
    assert _conv(c, n["gs301"])["Phòng 301 - A6"]["unread"] == 0  # tin của chính mình không thành chưa đọc
    j = c.get(f"/api/chat/messages?room_id={r301}&active=true", headers=auth(n["admin"])).get_json()
    assert [x["message"] for x in j["messages"]] == ["Máy 05 không vào được mạng"]
    assert c.get("/api/chat/unread", headers=auth(n["admin"])).get_json() == {"unread": 0}
    assert c.get("/api/chat/unread", headers=auth(n["it02"])).get_json() == {"unread": 1}  # admin khác chưa đọc
    c.post("/api/chat/send", json={"room_id": r301, "message": "IT xuống ngay"}, headers=auth(n["admin"]))
    assert c.get("/api/chat/unread", headers=auth(n["gs301"])).get_json() == {"unread": 1}
    assert c.get(f"/api/chat/messages?room_id={r301}", headers=auth(n["gs405"])).status_code == 404
    # poll chỉ tin mới
    j2 = c.get(f"/api/chat/messages?room_id={r301}&since={m['id']}", headers=auth(n["gs301"])).get_json()
    assert [(x["message"], x["is_admin"]) for x in j2["messages"]] == [("IT xuống ngay", True)]


def test_lab_va_hsk_cung_phong_khong_lan(world, db):
    _, _, rooms = _dung(world)
    c, n = world["c"], _nguoi(world, db, rooms)
    r301 = rooms["Phòng 301 - A6"]
    a = c.post("/api/chat/send", json={"room_id": r301, "message": "tin LAB"}, headers=auth(n["gs301"])).get_json()
    c.post("/api/chat/send", json={"scope": "HSK", "room_id": r301, "message": "tin HSK"}, headers=auth(n["gs301"]))
    lab = c.get(f"/api/chat/messages?room_id={r301}", headers=auth(n["admin"])).get_json()["messages"]
    hsk = c.get(f"/api/chat/messages?scope=HSK&room_id={r301}", headers=auth(n["admin"])).get_json()["messages"]
    assert [x["message"] for x in lab] == ["tin LAB"] and [x["message"] for x in hsk] == ["tin HSK"]
    assert _conv(c, n["admin"], "HSK")["Phòng 301 - A6"]["last"] == "tin HSK"
    c.get(f"/api/chat/messages?scope=HSK&room_id={r301}&active=1", headers=auth(n["admin"]))
    assert c.get("/api/chat/unread?scope=HSK", headers=auth(n["admin"])).get_json()["unread"] == 0
    assert c.get("/api/chat/unread?scope=LAB", headers=auth(n["admin"])).get_json()["unread"] == 1  # đọc HSK ≠ đọc LAB
    assert c.post("/api/chat/react", json={"scope": "HSK", "msg_id": a["id"], "emoji": "👍"},
                  headers=auth(n["admin"])).status_code == 404  # không thả cảm xúc chéo hệ
    r = c.post("/api/chat/clear", json={"scope": "HSK", "room_id": r301}, headers=auth(n["admin"]))
    assert r.status_code == 200
    assert [x["message"] for x in c.get(f"/api/chat/messages?room_id={r301}", headers=auth(n["admin"]))
            .get_json()["messages"]] == ["tin LAB"]  # xoá HSK không đụng LAB


def test_anh_cam_xuc_va_xoa(world, db):
    _, _, rooms = _dung(world)
    c, n = world["c"], _nguoi(world, db, rooms)
    r301 = rooms["Phòng 301 - A6"]
    m = c.post("/api/chat/send", json={"room_id": r301, "image": JPG}, headers=auth(n["gs301"])).get_json()
    assert m["image"] is True and m["message"] == ""
    assert _conv(c, n["admin"])["Phòng 301 - A6"]["last"] == "[Hình ảnh]"
    r = c.get(f"/api/chat/image/{m['id']}", headers=auth(n["admin"]))
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.data.startswith(b"\xff\xd8")
    r.close()  # trả tệp (Windows không cho xoá tệp đang mở)
    assert c.get(f"/api/chat/image/{m['id']}", headers=auth(n["gs405"])).status_code == 404
    for bad in ("data:text/html;base64,PGI+", "data:image/jpeg;base64,@@@", "khong-phai-anh"):
        r = c.post("/api/chat/send", json={"room_id": r301, "image": bad}, headers=auth(n["gs301"]))
        assert r.status_code == 400, bad
    r = c.post("/api/chat/send", json={"room_id": r301, "message": "  "}, headers=auth(n["gs301"]))
    assert r.status_code == 400
    # Cảm xúc: mỗi người một; bấm lại = bỏ
    for who, e in (("admin", "👍"), ("it02", "👍"), ("gs301", "❤️")):
        c.post("/api/chat/react", json={"msg_id": m["id"], "emoji": e}, headers=auth(n[who]))
    assert c.post("/api/chat/react", json={"msg_id": m["id"], "emoji": "😂"}, headers=auth(n["admin"])).get_json() == {
        "mine": "😂"}
    rx = c.get(f"/api/chat/messages?room_id={r301}", headers=auth(n["admin"])).get_json()["reactions"][m["id"]]
    assert rx == {"counts": {"👍": 1, "❤️": 1, "😂": 1}, "mine": "😂"}
    assert c.post("/api/chat/react", json={"msg_id": m["id"], "emoji": "😂"}, headers=auth(n["admin"])).get_json() == {
        "mine": ""}
    # Xoá: chỉ admin; xoá kèm ảnh + cảm xúc; keep = hội thoại rỗng vẫn trong danh sách
    assert c.post("/api/chat/clear", json={"room_id": r301}, headers=auth(n["gs301"])).status_code == 403
    j = c.post("/api/chat/clear", json={"room_id": r301, "keep": True}, headers=auth(n["admin"])).get_json()
    assert j["deleted"] == 1 and j["clear_token"] != "0"
    assert repo_for(db, world["tid"], "file_metadata").count({"scope": "storage", "area": "chat"}) == 0
    assert repo_for(db, world["tid"], "chat_reactions").count({}) == 0
    assert _conv(c, n["admin"])["Phòng 301 - A6"]["last"] == ""
    c.post("/api/chat/clear", json={"room_id": r301}, headers=auth(n["admin"]))
    assert _conv(c, n["admin"]) == {}


def test_realtime_chi_toi_dung_nguoi(world, db):
    _, _, rooms = _dung(world)
    c, n = world["c"], _nguoi(world, db, rooms)
    r301 = rooms["Phòng 301 - A6"]
    s = {who: k.browser(world["app"], n[who]) for who in ("admin", "it02", "gs301", "gs405")}
    for x in s.values():
        x.get_received(DESKTOP_NS)
    c.post("/api/chat/send", json={"room_id": r301, "message": "alo"}, headers=auth(n["gs301"]))
    ev = {who: k.got(x, "chat_event") for who, x in s.items()}
    assert ev["gs405"] == [] and len(ev["admin"]) == len(ev["it02"]) == len(ev["gs301"]) == 1
    assert {k_: ev["admin"][0][k_] for k_ in ("kind", "scope", "room_name", "from_admin", "preview")} == {
        "kind": "message", "scope": "LAB", "room_name": "Phòng 301 - A6", "from_admin": False, "preview": "alo"}


def test_xoa_khi_anh_dang_bi_giu_thi_don_luot_sau(world, db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.storage.sweeper import sweep

    _, _, rooms = _dung(world)
    c, n = world["c"], _nguoi(world, db, rooms)
    r301 = rooms["Phòng 301 - A6"]
    m = c.post("/api/chat/send", json={"room_id": r301, "image": JPG}, headers=auth(n["gs301"])).get_json()
    dang_tai = c.get(f"/api/chat/image/{m['id']}", headers=auth(n["admin"]))  # chưa đóng = tệp đang bị giữ
    # Windows không xoá được tệp đang mở (WinError 32); Linux (CI) thì xoá được → giả lập đúng lỗi đó ở kho tệp để test
    # chạy như nhau trên mọi hệ điều hành
    kho = world["app"].extensions["storage"]
    goc, giu = kho.delete, {"on": True}

    def delete(key):
        if giu["on"]:
            raise PermissionError(32, "Tệp đang được tiến trình khác sử dụng")
        return goc(key)

    monkeypatch.setattr(kho, "delete", delete)
    assert c.post("/api/chat/clear", json={"room_id": r301}, headers=auth(n["admin"])).status_code == 200
    so = repo_for(db, world["tid"], "file_metadata").find_one({"scope": "storage", "area": "chat"})
    assert so is not None and so["delete_after"] is not None  # chưa xoá được → hẹn worker
    dang_tai.close()
    giu["on"] = False
    assert sweep(db, world["app"].extensions["storage"], datetime.now(UTC) + timedelta(seconds=1)) == {"deleted": 1}
