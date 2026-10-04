# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Xem / điều khiển màn hình (Sổ tay 5.4): mở/đóng phiên (vnc_start/vnc_stop bọc command_obj, URL noVNC đúng bài học
hệ cũ), quyền remote.vnc + phạm vi phòng, máy mất kênh lệnh → 409; lưu bố trí lưới View desktop (room_map.edit)."""
from __future__ import annotations

import dataclasses
import re
from urllib.parse import parse_qs, urlparse

from bson import ObjectId

from app.devices.vnc import viewer_url
from app.legacy_adapter import contract as k
from app.rbac.service import create_policy
from app.realtime.hub import DESKTOP_NS
from app.tenants import service as tsvc
from tests.conftest import auth
from tests.unit.conftest import tok


def _may(w):
    for h, m in (("A6-301-01", "aa:bb:cc:00:30:01"), ("A6-405-01", "aa:bb:cc:00:40:01")):
        assert w["c"].post("/update", json=k.heartbeat(h, m)).status_code == 200
    w["ad"].writer_tick()
    t = tok(w)
    devs = {d["hostname"]: d["id"] for d in w["c"].get("/api/devices", headers=auth(t)).get_json()["items"]}
    rooms = {r["name"]: r["id"] for r in w["c"].get("/api/rooms", headers=auth(t)).get_json()["items"]}
    return devs, rooms


def test_url_novnc_giu_bai_hoc_he_cu():
    u = viewer_url("ab" * 32, "6xw2Yykq")
    q = parse_qs(urlparse(u).query)
    assert u.startswith("/novnc/vnc.html?")
    assert q["path"] == [f"/vncws?role=viewer&token={'ab' * 32}"]  # TUYỆT ĐỐI /vncws (bug 10/09 hệ cũ)
    assert "path=%2Fvncws%3Frole%3Dviewer%26token%3D" in u
    assert q["view_only"] == ["0"] and q["reconnect"] == ["true"] and q["quality"] == ["9"]
    assert q["password"] == ["6xw2Yykq"] and q["autoconnect"] == ["1"]
    assert viewer_url("t", "p", "https://10.21.24.142:7443").startswith("https://10.21.24.142:7443/novnc/vnc.html?")


def test_mo_va_dong_phien_tren_may_dang_online(world):
    devs, _ = _may(world)
    ag = k.agent(world["app"])  # A6-301-01 có socket
    ag.get_received()
    c, t = world["c"], tok(world)
    r = c.post(f"/api/devices/{devs['A6-301-01']}/vnc/open", headers=auth(t))
    j = r.get_json()
    assert r.status_code == 200 and j["channel"] == "socket" and re.fullmatch(r"[0-9a-f]{64}", j["token"])
    cmd = k.got(ag, "execute_command")[0]
    assert cmd["hostname"] == "A6-301-01" and "action" not in cmd  # PHẢI bọc command_obj (bug 11/09 hệ cũ)
    assert cmd["command_obj"] == {"action": "vnc_start", "relay_url": "wss://10.21.24.142:5443/vncws",
                                  "token": j["token"]}
    assert f"token%3D{j['token']}" in j["viewer_url"] and j["viewer_url"].startswith("/novnc/vnc.html?")
    r = c.post(f"/api/devices/{devs['A6-301-01']}/vnc/close", json={"token": j["token"]}, headers=auth(t))
    assert r.status_code == 200 and k.got(ag, "execute_command")[0]["command_obj"] == {"action": "vnc_stop"}
    # Đặt gốc web xem riêng (vd :5443 khi Desktop chạy cùng máy chủ) → URL tuyệt đối
    world["app"].config["ITM_SETTINGS"] = dataclasses.replace(world["app"].config["ITM_SETTINGS"],
                                                              VNC_VIEWER_BASE="https://10.21.24.142:5443")
    j = c.post(f"/api/devices/{devs['A6-301-01']}/vnc/open", headers=auth(t)).get_json()
    assert j["viewer_url"].startswith("https://10.21.24.142:5443/novnc/vnc.html?")


def test_quyen_pham_vi_va_may_mat_kenh(world, db):
    devs, rooms = _may(world)
    c, t = world["c"], tok(world)
    world["clock"][0] += 120  # quá hạn nhịp tim → máy tắt, không còn kênh lệnh
    r = c.post(f"/api/devices/{devs['A6-405-01']}/vnc/open", headers=auth(t))
    assert r.status_code == 409
    assert c.post("/api/devices/khong-co/vnc/open", headers=auth(t)).status_code == 404
    staff = tok(world, user="gv01", pw="Gv@12345")  # policy chỉ xem, không có remote.vnc
    assert c.post(f"/api/devices/{devs['A6-301-01']}/vnc/open", headers=auth(staff)).status_code == 403
    pid = create_policy(db, world["tid"], "GS 405", permission_codes=["remote.vnc"],
                        room_ids=[ObjectId(rooms["Phòng 405 - A6"])])["_id"]
    tsvc.create_user(db, world["tid"], "gs405", password="Gs@12345", policy_ids=[pid])
    g = tok(world, user="gs405", pw="Gs@12345")
    assert c.post(f"/api/devices/{devs['A6-301-01']}/vnc/open", headers=auth(g)).status_code == 404  # ngoài phạm vi
    tb = tok(world, tenant="BBB")
    assert c.post(f"/api/devices/{devs['A6-301-01']}/vnc/open", headers=auth(tb)).status_code == 404  # tổ chức khác
    assert c.post(f"/api/devices/{devs['A6-301-01']}/vnc/close", json={}, headers=auth(staff)).status_code == 403


def test_luu_bo_tri_luoi_view_desktop(world):
    _, rooms = _may(world)
    c, t, rid = world["c"], tok(world), rooms["Phòng 301 - A6"]
    d = k.browser(world["app"], t)
    assert d.emit("subscribe_room", {"room_id": rid}, namespace=DESKTOP_NS, callback=True)["ok"]
    d.get_received(DESKTOP_NS)
    body = {"layout": {"a6-301-01": {"fx": 1.23456, "fy": 0}, "A6-301-02": {"fx": -1, "fy": 0},
                       "A6-301-03": {"fx": "x"}, "A6-301-04": "rac", "A6-301-GV": {"fx": 2.5, "fy": 3.25}}}
    r = c.put(f"/api/rooms/{rid}/live-layout", json=body, headers=auth(t))
    assert r.status_code == 200 and r.get_json() == {"ok": True, "count": 2}
    room = c.get(f"/api/rooms/{rid}", headers=auth(t)).get_json()
    assert room["live_layout"] == {"A6-301-01": {"fx": 1.235, "fy": 0.0}, "A6-301-GV": {"fx": 2.5, "fy": 3.25}}
    assert k.got(d, "room_map_updated")[-1] == {"room_id": rid, "by": "admin", "what": "live_layout"}
    staff = tok(world, user="gv01", pw="Gv@12345")
    assert c.put(f"/api/rooms/{rid}/live-layout", json=body, headers=auth(staff)).status_code == 403
