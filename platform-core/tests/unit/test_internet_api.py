# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Internet (Sổ tay 6.3, luật §0): lệnh internet_control đúng dạng hub cũ, cả phòng chừa máy GV, website bắt buộc khi
chặn web, và CHỐT §0 — đường agent gọi về máy chủ nằm trong cổng agent sẽ chặn thì TỪ CHỐI lệnh ngắt Internet."""
from __future__ import annotations

import dataclasses

from app.control.internet import unsafe_reason
from app.legacy_adapter import contract as k
from tests.conftest import auth
from tests.unit.conftest import tok
from tests.unit.test_power_api import _dung


def test_chot_0_duong_ve_may_chu_khong_nam_trong_cong_bi_chan():
    assert unsafe_reason("wss://10.21.24.142:5443/vncws") is None  # cấu hình đang chạy: agent ra 5443
    assert unsafe_reason("wss://10.21.24.142:7443/vncws") is None
    for bad in ("wss://10.21.24.142/vncws", "wss://10.21.24.142:443/vncws", "ws://10.21.24.142:8080/x",
                "https://may-chu:8443/x"):
        assert unsafe_reason(bad), bad


def test_ngat_mo_internet_va_chan_web(world):
    ag, devs, rooms = _dung(world)
    c, t = world["c"], tok(world)
    j = c.post("/api/internet", json={"room_id": rooms["Phòng 301 - A6"], "action": "disable"},
               headers=auth(t)).get_json()
    assert j["sent"] == [{"hostname": "A6-301-01", "channel": "socket"}]
    assert {s["hostname"] for s in j["skipped"]} == {"A6-301-GV", "A6-301-02"}
    co = k.got(ag["A6-301-01"], "execute_command")[0]["command_obj"]
    assert co == {"action": "internet_control", "sub_action": "disable", "websites": ""}
    assert c.post("/api/internet", json={"device_ids": [devs["A6-301-01"]], "action": "block_web", "websites": "  "},
                  headers=auth(t)).status_code == 422
    j = c.post("/api/internet", json={"device_ids": [devs["A6-301-GV"]], "action": "block_web",
                                      "websites": "facebook.com, youtube.com\n"}, headers=auth(t)).get_json()
    assert j["sent"] == [{"hostname": "A6-301-GV", "channel": "socket"}]  # chọn đích danh máy GV thì vẫn gửi
    assert k.got(ag["A6-301-GV"], "execute_command")[0]["command_obj"]["websites"] == "facebook.com, youtube.com"
    staff = tok(world, user="gv01", pw="Gv@12345")
    assert c.post("/api/internet", json={"room_id": rooms["Phòng 301 - A6"], "action": "enable"},
                  headers=auth(staff)).status_code == 403


def test_tu_choi_ngat_internet_khi_cau_hinh_nguy_hiem(world):
    ag, _, rooms = _dung(world)
    world["app"].config["ITM_SETTINGS"] = dataclasses.replace(world["app"].config["ITM_SETTINGS"],
                                                              VNC_RELAY_PUBLIC="wss://10.21.24.142/vncws")
    r = world["c"].post("/api/internet", json={"room_id": rooms["Phòng 301 - A6"], "action": "disable"},
                        headers=auth(tok(world)))
    assert r.status_code == 409 and "§0" in r.get_json()["message"]
    assert not k.got(ag["A6-301-01"], "execute_command")  # KHÔNG gửi gì
    r = world["c"].post("/api/internet", json={"room_id": rooms["Phòng 301 - A6"], "action": "enable"},
                        headers=auth(tok(world)))
    assert r.status_code == 200  # MỞ Internet luôn được phép (đường cứu máy)
