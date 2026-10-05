# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Sổ tay 7.2 (Core): trình quản lý tệp 2 khung — token truyền tệp, máy bạn ↔ máy trạm qua kho chung, chốt token ở relay
`fs_request`, nhận ra máy đang ngồi, khung "Máy chủ" = kho riêng của tổ chức (Super Admin)."""
from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta

from bson import ObjectId

from app.legacy_adapter import contract as k
from app.rbac.service import create_policy
from app.realtime.hub import DESKTOP_NS
from app.tenants import service as tsvc
from app.tenants.repo import repo_for
from tests.conftest import auth
from tests.unit.conftest import tok
from tests.unit.test_power_api import MAY, _dung


def _gs301(world, db, rooms):
    pid = create_policy(db, world["tid"], "GS 301", permission_codes=["device.control"],
                        room_ids=[ObjectId(rooms["Phòng 301 - A6"])])["_id"]
    tsvc.create_user(db, world["tid"], "gs301", password="Gs@12345", policy_ids=[pid])
    return tok(world, user="gs301", pw="Gs@12345")


# ====================================================================== máy bạn ↔ máy trạm
def test_token_tai_len_tai_ve_qua_kho_chung(world, db):
    _, _, rooms = _dung(world)
    c, t = world["c"], tok(world)
    tk = c.post("/api/files/token", headers=auth(t)).get_json()["token"]
    assert c.get(f"/api/files/pulled/{tk}", headers=auth(t)).get_json()["status"] == "pending"  # agent chưa nộp
    assert c.post(f"/fs_recv_raw?token={tk}&name=Bài làm.docx", data=b"PK bai").get_json() == {"status": "ok"}
    r = c.get(f"/api/files/pulled/{tk}", headers=auth(t))
    assert r.status_code == 200 and r.data == b"PK bai"
    assert "B%C3%A0i%20l%C3%A0m.docx" in r.headers["Content-Disposition"]
    g = _gs301(world, db, rooms)
    assert c.get(f"/api/files/pulled/{tk}", headers=auth(g)).status_code == 404  # token của người khác
    # Máy bạn → Core → máy trạm tải /fs_serve (agent v2 không đổi gì)
    j = c.post("/api/files/upload?name=Đề thi: số 1.docx", data=b"de thi", headers=auth(t)).get_json()
    assert j["filename"] == "Đề thi_ số 1.docx" and j["size"] == 6
    assert c.get(f"/fs_serve/{j['token']}").data == b"de thi"
    doc = repo_for(db, world["tid"], "file_metadata").find_one({"scope": "fs_token", "token": j["token"]})
    assert doc["user"] and doc["push_key"].startswith(f"tenants/{world['tid']}/temp/fs/")


def test_relay_fs_request_chot_token(world):
    ag, devs, _ = _dung(world)
    c, t = world["c"], tok(world)
    did = devs["A6-301-01"]
    d = k.browser(world["app"], t)
    assert d.emit("fs_request", {"device_id": did, "op": "list", "req_id": "r1", "path": "C:\\"},
                  namespace=DESKTOP_NS, callback=True) == {"ok": True}
    q = k.got(ag["A6-301-01"], "fs_request")[0]
    assert q["op"] == "list" and q["hostname"] == "A6-301-01" and q["reply_sid"]
    for bad in ({"op": "push", "download_url": "/download_setup"}, {"op": "push", "download_url": "/fs_serve/abcdef12"},
                {"op": "pull", "token": "deadbeef"}, {"op": "pull"}):
        r = d.emit("fs_request", {"device_id": did, "req_id": "x", "target": "C:\\a", "folder": "C:\\", **bad},
                   namespace=DESKTOP_NS, callback=True)
        assert r["ok"] is False and "Token" in r["error"], bad
    assert k.got(ag["A6-301-01"], "fs_request") == []  # không lệnh xấu nào tới máy
    up = c.post("/api/files/upload?name=a.txt", data=b"x", headers=auth(t)).get_json()
    assert d.emit("fs_request", {"device_id": did, "op": "push", "req_id": "r2", "folder": "C:\\Users",
                                 "filename": "a.txt", "download_url": f"/fs_serve/{up['token']}"},
                  namespace=DESKTOP_NS, callback=True)["ok"]
    q = k.got(ag["A6-301-01"], "fs_request")[0]
    d.get_received(DESKTOP_NS)
    ag["A6-301-01"].emit("fs_response", {"req_id": "r2", "reply_sid": q["reply_sid"], "op": "push", "ok": True})
    assert k.got(d, "fs_response") == [{"req_id": "r2", "op": "push", "ok": True}]


def test_whoami_nhan_ra_may_dang_ngoi(world, db):
    _, _, rooms = _dung(world)
    c, t = world["c"], tok(world)
    j = c.get("/api/files/whoami", headers={**auth(t), "X-Forwarded-For": MAY["A6-301-01"][1]}).get_json()
    assert j["super"] is True and j["self_device"]["hostname"] == "A6-301-01"
    j = c.get("/api/files/whoami", headers={**auth(t), "X-Forwarded-For": MAY["A6-301-02"][1]}).get_json()
    assert j["self_device"] is None  # máy đó đang tắt → không coi là "máy này"
    g = _gs301(world, db, rooms)
    assert c.get("/api/files/whoami", headers=auth(g)).get_json()["super"] is False
    assert c.post("/api/files/srv", json={"op": "list"}, headers=auth(g)).status_code == 403  # khung Máy chủ


# ====================================================================== khung "Máy chủ" = kho riêng của tổ chức
def _srv(c, t, **kw):
    return c.post("/api/files/srv", json=kw, headers=auth(t)).get_json()


def test_may_chu_la_kho_rieng_thao_tac_nhu_explorer(world, db):
    c, t = world["c"], tok(world)
    assert _srv(c, t, op="list") == {"ok": True, "error": "", "op": "list", "path": "", "items": []}
    assert _srv(c, t, op="mkdir", path="", name="Đề thi")["ok"]
    assert _srv(c, t, op="mkdir", path="", name="đề THI")["name"] == "Đề thi"  # trùng (khác hoa/thường) = đã có
    assert c.post("/api/files/srv/upload?path=Đề thi&name=bài 1.docx", data=b"111", headers=auth(t)).get_json()["ok"]
    assert c.post("/api/files/srv/upload?path=Đề thi&name=BÀI 1.docx", data=b"222", headers=auth(t)).get_json()[
        "name"] == "bài 1.docx"  # ghi đè đúng tệp cũ, không đẻ tệp thứ hai
    assert _srv(c, t, op="mkdir", path="Đề thi", name="Trống")["ok"]
    ls = _srv(c, t, op="list", path="Đề thi")
    assert ls["path"] == "Đề thi" and [(i["name"], i["type"], i["size"]) for i in ls["items"]] == [
        ("Trống", "dir", 0), ("bài 1.docx", "file", 3)]
    assert [i["name"] for i in _srv(c, t, op="list")["items"]] == ["Đề thi"]
    r = c.get("/api/files/srv/download?path=Đề thi\\bài 1.docx", headers=auth(t))
    assert r.status_code == 200 and r.data == b"222"
    # Tên sai luật → báo lỗi, KHÔNG tự sửa ngầm
    for bad in ({"op": "mkdir", "path": "", "name": "a:b"}, {"op": "mkdir", "path": "..", "name": "x"},
                {"op": "rename", "src": "Đề thi", "dst": "Đề thi\\con"}, {"op": "list", "path": "Không có"}):
        assert _srv(c, t, **bad)["ok"] is False, bad
    assert _srv(c, t, op="copy", src="Đề thi", dst="Bản sao")["ok"]
    assert _srv(c, t, op="rename", src="Bản sao\\bài 1.docx", dst="Bản sao\\bài 2.docx")["ok"]
    assert _srv(c, t, op="rename", src="Bản sao", dst="Đề THI")["ok"] is False  # đích trùng tên
    assert _srv(c, t, op="rename", src="Bản sao", dst="bản sao")["ok"]  # đổi hoa/thường chính nó
    assert [(i["name"], i["type"]) for i in _srv(c, t, op="list", path="bản sao")["items"]] == [
        ("Trống", "dir"), ("bài 2.docx", "file")]
    # Thùng rác: xoá mềm 30 ngày, trùng tên tự đánh số; xoá trong Thùng rác = xoá hẳn
    assert _srv(c, t, op="recycle", target="bản sao")["name"] == "bản sao"
    assert c.post("/api/files/srv/upload?path=&name=bản sao", data=b"f", headers=auth(t)).get_json()["ok"]
    assert _srv(c, t, op="recycle", target="bản sao")["name"] == "bản sao (2)"
    trash = repo_for(db, world["tid"], "file_metadata").find({"scope": "storage", "key": {"$regex": "Thùng rác"}})
    now = datetime.now(UTC)
    for x in trash:
        da = x["delete_after"] if x["delete_after"].tzinfo else x["delete_after"].replace(tzinfo=UTC)
        assert timedelta(days=29) < da - now <= timedelta(days=30)
    assert _srv(c, t, op="rename", src="Thùng rác\\bản sao", dst="Khôi phục")["ok"]  # chuyển ra → hết hạn dọn
    assert repo_for(db, world["tid"], "file_metadata").find_one({"key": {"$regex": "/drive/Khôi phục/bài 2"}})[
        "delete_after"] is None
    assert _srv(c, t, op="recycle", target="Thùng rác\\bản sao (2)")["ok"]  # trong Thùng rác → xoá hẳn
    assert _srv(c, t, op="delete", target="Khôi phục")["ok"]
    assert [i["name"] for i in _srv(c, t, op="list")["items"]] == ["Đề thi"]


def test_may_chu_voi_may_tram_stage_va_land(world, db):
    c, t = world["c"], tok(world)
    _srv(c, t, op="mkdir", path="", name="Đề thi")
    _srv(c, t, op="mkdir", path="Đề thi", name="Rỗng")
    c.post("/api/files/srv/upload?path=Đề thi&name=de.docx", data=b"DE", headers=auth(t))
    c.post("/api/files/srv/upload?path=Đề thi\\Nghe&name=a.mp3", data=b"MP3", headers=auth(t))
    # Máy chủ → máy trạm: tệp phục vụ thẳng từ kho (không chép); thư mục nén .zip giữ cả thư mục rỗng
    s = _srv(c, t, op="stage", target="Đề thi\\de.docx")
    assert s["ok"] and not s["zipped"] and c.get(f"/fs_serve/{s['token']}").data == b"DE"
    s = _srv(c, t, op="stage", target="Đề thi")
    assert s["zipped"] and s["filename"] == "Đề thi"
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/fs_serve/{s['token']}").data))
    assert sorted(z.namelist()) == ["Nghe/a.mp3", "Rỗng/", "de.docx"] and z.read("Nghe/a.mp3") == b"MP3"
    # Máy trạm → máy chủ: tệp lẻ hạ vào thư mục (trùng tên tự đánh số), gói .zip giải nén chống zip-slip
    tk = c.post("/api/files/token", headers=auth(t)).get_json()["token"]
    c.post(f"/fs_recv_raw?token={tk}&name=de.docx", data=b"BAI")
    j = _srv(c, t, op="land", token=tk, folder="Đề thi", filename="de.docx", zipped=False)
    assert j["ok"] and j["name"] == "de (2).docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zw:
        zw.writestr("bai/cau1.txt", "c1")
        zw.writestr("../../thoat.txt", "xau")
        zw.writestr("bai/trong/", "")
    tk = c.post("/api/files/token", headers=auth(t)).get_json()["token"]
    c.post(f"/fs_recv_raw?token={tk}&name=A6-301-01.zip", data=buf.getvalue())
    assert _srv(c, t, op="land", token=tk, folder="Bài thu", filename="A6-301-01", zipped=True)["ok"]
    keys = sorted(x["key"].split("/drive/")[1] for x in repo_for(db, world["tid"], "file_metadata").find(
        {"scope": "storage", "area": "drive", "key": {"$regex": "/Bài thu/"}}))
    assert keys == ["Bài thu/A6-301-01/bai/cau1.txt", "Bài thu/A6-301-01/bai/trong/.folder",
                    "Bài thu/A6-301-01/thoat.txt"]  # "../../" bị gỡ — không thoát ra ngoài thư mục đích
    assert repo_for(db, world["tid"], "file_metadata").count({"scope": "storage", "area": "temp",
                                                              "key": {"$regex": tk}}) == 0  # gói tạm đã dọn
    assert _srv(c, t, op="land", token=tk, folder="x", filename="y")["error"].startswith("Máy trạm chưa nộp xong")
