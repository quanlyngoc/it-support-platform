# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Nguồn + Wake-on-LAN (Sổ tay 6.1): tắt/khởi động lại cả phòng chừa máy GV, ghi "tắt có chủ ý" lúc ra lệnh, bật máy
qua máy trung gian CÙNG subnet (relay_wake_batch, tối đa 2 máy/subnet), subnet không có máy bật → báo rõ, quyền + phạm
vi."""
from __future__ import annotations

from bson import ObjectId

from app.legacy_adapter import contract as k
from app.rbac.service import create_policy
from app.tenants import service as tsvc
from tests.conftest import auth
from tests.unit.conftest import tok

MAY = {"A6-301-01": ("aa:bb:cc:00:30:01", "10.6.41.11"), "A6-301-02": ("aa:bb:cc:00:30:02", "10.6.41.12"),
       "A6-301-GV": ("aa:bb:cc:00:30:99", "10.6.41.13"), "A6-405-01": ("aa:bb:cc:00:40:01", "10.6.42.11")}


def _dung(w):
    """Cả 4 máy báo nhịp tim → lưu; 36 s sau chỉ 301-01 và 301-GV còn bật (có socket); 301-02, 405-01 tắt."""
    for h, (m, ip) in MAY.items():
        assert w["c"].post("/update", json=k.heartbeat(h, m, ip=ip)).status_code == 200
    w["ad"].writer_tick()
    w["clock"][0] += 36
    ag = {}
    for h in ("A6-301-01", "A6-301-GV"):
        ag[h] = k.agent(w["app"], h, MAY[h][0])  # agent giả tự gửi nhịp tim IP mặc định → nạp lại IP thật SAU đó
        w["ad"].state.ingest(k.heartbeat(h, MAY[h][0], ip=MAY[h][1]), "127.0.0.1")
        ag[h].get_received()
    t = tok(w)
    devs = {d["hostname"]: d["id"] for d in w["c"].get("/api/devices", headers=auth(t)).get_json()["items"]}
    rooms = {r["name"]: r["id"] for r in w["c"].get("/api/rooms", headers=auth(t)).get_json()["items"]}
    return ag, devs, rooms


def _lenh(client):
    return [e for e in k.got(client, "execute_command")]


def test_tat_ca_phong_chua_may_gv_va_ghi_tat_co_chu_y(world):
    ag, _, rooms = _dung(world)
    c, t = world["c"], tok(world)
    r = c.post("/api/power", json={"action": "shutdown", "room_id": rooms["Phòng 301 - A6"]}, headers=auth(t))
    j = r.get_json()
    assert r.status_code == 200 and j["sent"] == [{"hostname": "A6-301-01", "channel": "socket"}]
    assert {(s["hostname"], s["reason"]) for s in j["skipped"]} == {("A6-301-GV", "máy giảng viên"),
                                                                   ("A6-301-02", "máy đang tắt")}
    assert [e["command"] for e in _lenh(ag["A6-301-01"])] == ["shutdown"] and not _lenh(ag["A6-301-GV"])
    assert world["ad"].tat_sach_since("A6-301-01") is not None  # ghi NGAY lúc ra lệnh (không đợi máy báo)
    j = c.post("/api/power", json={"action": "restart", "room_id": rooms["Phòng 301 - A6"], "exclude_gv": False},
               headers=auth(t)).get_json()
    assert {s["hostname"] for s in j["sent"]} == {"A6-301-01", "A6-301-GV"}
    assert [e["command"] for e in _lenh(ag["A6-301-GV"])] == ["restart"]


def test_bat_may_qua_may_trung_gian_cung_subnet(world):
    ag, devs, rooms = _dung(world)
    c, t = world["c"], tok(world)
    j = c.post("/api/power", json={"action": "wake", "room_id": rooms["Phòng 301 - A6"]}, headers=auth(t)).get_json()
    assert j["targets"] == 1 and j["no_helper"] == []
    assert {h["helper"] for h in j["helpers"]} == {"A6-301-01", "A6-301-GV"}  # GV không bị bật nhưng VẪN bắn hộ được
    assert all(h["subnet"] == "10.6.41" for h in j["helpers"])
    for h in ("A6-301-01", "A6-301-GV"):
        co = _lenh(ag[h])[0]["command_obj"]
        assert co == {"action": "relay_wake_batch", "targets": [{"mac": "aa:bb:cc:00:30:02", "ip": "10.6.41.12"}]}
    # Máy subnet khác, không máy nào bật cùng subnet/phòng → báo rõ, KHÔNG bắn từ máy chủ
    j = c.post("/api/power", json={"action": "wake", "device_ids": [devs["A6-405-01"]]}, headers=auth(t)).get_json()
    assert j["no_helper"] == ["A6-405-01"] and j["helpers"] == []
    j = c.post("/api/power", json={"action": "wake", "device_ids": [devs["A6-301-01"], "khong-co"]},
               headers=auth(t)).get_json()
    assert {(s.get("hostname") or s.get("id"), s["reason"]) for s in j["skipped"]} == {
        ("A6-301-01", "máy đang bật"), ("khong-co", "không có máy này")}


def test_quyen_pham_vi_va_dau_vao(world, db):
    _, devs, rooms = _dung(world)
    c, t = world["c"], tok(world)
    assert c.post("/api/power", json={"action": "shutdown"}, headers=auth(t)).status_code == 422
    both = {"action": "shutdown", "room_id": rooms["Phòng 301 - A6"], "device_ids": [devs["A6-301-01"]]}
    assert c.post("/api/power", json=both, headers=auth(t)).status_code == 422
    assert c.post("/api/power", json={"action": "format", "room_id": rooms["Phòng 301 - A6"]},
                  headers=auth(t)).status_code == 422
    assert c.post("/api/power", json={"action": "shutdown", "room_id": "khong-phai-id"},
                  headers=auth(t)).status_code == 404
    staff = tok(world, user="gv01", pw="Gv@12345")
    assert c.post("/api/power", json={"action": "shutdown", "room_id": rooms["Phòng 301 - A6"]},
                  headers=auth(staff)).status_code == 403
    pid = create_policy(db, world["tid"], "GS 405", permission_codes=["device.control"],
                        room_ids=[ObjectId(rooms["Phòng 405 - A6"])])["_id"]
    tsvc.create_user(db, world["tid"], "gs405", password="Gs@12345", policy_ids=[pid])
    g = tok(world, user="gs405", pw="Gs@12345")
    assert c.post("/api/power", json={"action": "shutdown", "room_id": rooms["Phòng 301 - A6"]},
                  headers=auth(g)).status_code == 404  # phòng ngoài phạm vi
    j = c.post("/api/power", json={"action": "shutdown", "device_ids": [devs["A6-301-01"]]}, headers=auth(g)).get_json()
    assert j["sent"] == [] and j["skipped"] == [{"id": devs["A6-301-01"], "reason": "không có máy này"}]
    tb = tok(world, tenant="BBB")
    assert c.post("/api/power", json={"action": "shutdown", "device_ids": [devs["A6-301-01"]]},
                  headers=auth(tb)).status_code == 409  # tổ chức không gắn agent v2
