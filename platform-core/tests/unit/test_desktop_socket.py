# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Kênh realtime Desktop — namespace /desktop: xác thực bằng token, phạm vi phòng, quyền, điều khiển trúng đích."""
from __future__ import annotations

from bson import ObjectId

from app.legacy_adapter import contract as k
from app.rbac.service import create_policy
from app.realtime.hub import DESKTOP_NS, socketio
from app.tenants import service as tsvc
from tests.conftest import auth
from tests.unit.conftest import tok


def _phong(w):
    for h, m in (("A6-301-01", "aa:bb:cc:00:30:01"), ("A6-405-01", "aa:bb:cc:00:40:01")):
        w["c"].post("/update", json=k.heartbeat(h, m))
    w["ad"].writer_tick()
    rooms = w["c"].get("/api/rooms", headers=auth(tok(w))).get_json()["items"]
    devs = w["c"].get("/api/devices", headers=auth(tok(w))).get_json()["items"]
    return {r["name"]: r["id"] for r in rooms}, {d["hostname"]: d["id"] for d in devs}


def _desk(w, token):
    return k.browser(w["app"], token)


def test_khong_token_hoac_token_rac_bi_tu_choi(world):
    for a in (None, {"token": "rac"}):
        c = socketio.test_client(world["app"], namespace=DESKTOP_NS, auth=a)
        assert not c.is_connected(DESKTOP_NS)


def test_super_admin_nhan_so_dem_toan_truong(world):
    d = _desk(world, tok(world))
    assert d.is_connected(DESKTOP_NS)
    _phong(world)
    tong = k.got(d, "batch_device_update")
    assert tong and tong[-1]["total_online"] == 2


def test_dang_ky_phong_theo_pham_vi_policy(world, db):
    phong, _ = _phong(world)
    pid = create_policy(db, world["tid"], "GS 301", permission_codes=["user.view"],
                        room_ids=[ObjectId(phong["Phòng 301 - A6"])])["_id"]
    tsvc.create_user(db, world["tid"], "gs301", password="Gs@12345", policy_ids=[pid])
    d = _desk(world, tok(world, user="gs301", pw="Gs@12345"))
    ack = d.emit("subscribe_room", {"room_id": phong["Phòng 405 - A6"]}, namespace=DESKTOP_NS, callback=True)
    assert ack["ok"] is False
    assert d.emit("subscribe_room", {"room_id": phong["Phòng 301 - A6"]}, namespace=DESKTOP_NS, callback=True)["ok"]
    d.get_received(DESKTOP_NS)
    world["clock"][0] += 61
    world["c"].post("/update", json=k.heartbeat("A6-301-01", "aa:bb:cc:00:30:01"))
    world["c"].post("/update", json=k.heartbeat("A6-405-01", "aa:bb:cc:00:40:01"))
    world["ad"].writer_tick()
    goi = k.got(d, "batch_device_update")
    assert goi and all(p.get("room_id") == phong["Phòng 301 - A6"] for p in goi)  # không nhận phòng ngoài phạm vi,
    # cũng không vào phòng tổng toàn trường (policy giới hạn phòng)


def test_dieu_khien_trung_dich_va_kiem_quyen(world):
    _, may = _phong(world)
    ag = k.agent(world["app"])  # A6-301-01 có socket
    khac = k.agent(world["app"], k.OTHER_HOST, k.OTHER_MAC)
    ag.get_received()
    khac.get_received()
    d = _desk(world, tok(world))
    r = d.emit("pty_input", {"device_id": may["A6-301-01"], "data": "dir\r"}, namespace=DESKTOP_NS, callback=True)
    assert r == {"ok": True}
    assert k.got(ag, "server_pty_input") == [{"mac": "aa:bb:cc:00:30:01", "hostname": "A6-301-01", "data": "dir\r"}]
    assert not k.got(khac, "server_pty_input")
    r = d.emit("pty_input", {"device_id": may["A6-405-01"], "data": "x"}, namespace=DESKTOP_NS, callback=True)
    assert r["ok"] is False and "socket" in r["error"]  # còn nhịp tim nhưng không có socket → báo rõ, không broadcast
    staff = _desk(world, tok(world, user="gv01", pw="Gv@12345"))
    r = staff.emit("pty_input", {"device_id": may["A6-301-01"], "data": "x"}, namespace=DESKTOP_NS, callback=True)
    assert r == {"ok": False, "error": "Không đủ quyền"} and not k.got(ag, "server_pty_input")
    bb = _desk(world, tok(world, "BBB"))  # tổ chức khác: kể cả Super Admin của họ cũng không chạm được máy
    r = bb.emit("pty_input", {"device_id": may["A6-301-01"], "data": "x"}, namespace=DESKTOP_NS, callback=True)
    assert r["ok"] is False and not k.got(ag, "server_pty_input")


def test_trinh_duyet_tep_va_anh_man_hinh_ve_dung_nguoi_hoi(world):
    _, may = _phong(world)
    ag = k.agent(world["app"])
    ag.get_received()
    hoi, nguoi_khac = _desk(world, tok(world)), _desk(world, tok(world))
    r = hoi.emit("fs_request", {"device_id": may["A6-301-01"], "op": "list", "path": "C:\\", "req_id": "r1",
                                "reply_sid": "gia-mao", "lenh_la": 1}, namespace=DESKTOP_NS, callback=True)
    assert r == {"ok": True}
    req = k.got(ag, "fs_request")[0]
    assert req["reply_sid"] == k.sid_of(hoi) and "lenh_la" not in req  # reply_sid do SERVER gắn; khoá lạ bị bỏ
    ag.emit("fs_response", {"req_id": "r1", "reply_sid": req["reply_sid"], "ok": True, "items": []})
    assert k.got(hoi, "fs_response") and not k.got(nguoi_khac, "fs_response")
    assert hoi.emit("fs_request", {"device_id": may["A6-301-01"], "op": "format_c"}, namespace=DESKTOP_NS,
                    callback=True)["ok"] is False
    r = hoi.emit("vnc_thumb_req", {"device_id": may["A6-301-01"], "hd": True}, namespace=DESKTOP_NS, callback=True)
    assert r == {"ok": True} and k.got(ag, "vnc_thumb_req")[0] == {"hostname": "A6-301-01",
                                                                  "reply_sid": k.sid_of(hoi), "hd": True}


def test_xem_luong_powershell_cua_may(world):
    _, may = _phong(world)
    ag = k.agent(world["app"])
    d = _desk(world, tok(world))
    assert d.emit("watch_device", {"device_id": may["A6-301-01"], "kind": "ps"}, namespace=DESKTOP_NS,
                  callback=True) == {"ok": True}
    ag.emit("client_ps_output", {"mac": "aa:bb:cc:00:30:01", "data": "PS C:\\> "})
    assert k.got(d, "ps_output") == [{"mac": "aa:bb:cc:00:30:01", "data": "PS C:\\> "}]


def test_dang_xuat_la_mat_quyen_ngay(world):
    _, may = _phong(world)
    k.agent(world["app"])
    t = tok(world)
    d = _desk(world, t)
    assert world["c"].post("/api/auth/logout", headers=auth(t)).status_code == 200
    r = d.emit("pty_input", {"device_id": may["A6-301-01"], "data": "x"}, namespace=DESKTOP_NS, callback=True)
    assert r["ok"] is False and not d.is_connected(DESKTOP_NS)
