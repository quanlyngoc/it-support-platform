# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Đăng nhập / đăng xuất từ xa (Sổ tay 6.2): bản mã AES-GCM đúng định dạng agent giải (nonce 12 B + ciphertext, hex),
thiếu khoá → 503, kết quả /login_result về ĐÚNG người bấm (room riêng), đăng xuất `{"command": "logout"}`, quyền."""
from __future__ import annotations

import dataclasses
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.legacy_adapter import contract as k
from app.realtime.hub import DESKTOP_NS
from app.tenants import service as tsvc
from tests.conftest import auth
from tests.unit.conftest import tok
from tests.unit.test_power_api import MAY, _dung

KEY = os.urandom(32).hex()


def _co_khoa(w):
    w["app"].config["ITM_SETTINGS"] = dataclasses.replace(w["app"].config["ITM_SETTINGS"], AES_256_KEY_HEX=KEY)


def test_thieu_khoa_aes_thi_tu_choi_ro_rang(world):
    _, _, rooms = _dung(world)
    r = world["c"].post("/api/remote-login", json={"room_id": rooms["Phòng 301 - A6"], "user": "SV", "password": "x"},
                        headers=auth(tok(world)))
    assert r.status_code == 503 and "AES_256_KEY_HEX" in r.get_json()["message"]


def test_dang_nhap_ma_hoa_va_ket_qua_ve_dung_nguoi_bam(world):
    ag, _, rooms = _dung(world)
    _co_khoa(world)
    c, t = world["c"], tok(world)
    tsvc.create_user(world["app"].extensions["itm_db"], world["tid"], "it02", password="It@12345",
                     policy_ids=[world["t"]["P"]["super_pid"]])
    nguoi_bam, nguoi_khac = k.browser(world["app"], t), k.browser(world["app"], tok(world, user="it02", pw="It@12345"))
    for d in (nguoi_bam, nguoi_khac):
        d.get_received(DESKTOP_NS)
    pw = 'P@ss "khó" $x`'
    r = c.post("/api/remote-login", json={"room_id": rooms["Phòng 301 - A6"], "user": "SV", "password": pw},
               headers=auth(t))
    j = r.get_json()
    assert r.status_code == 200 and j["sent"] == [{"hostname": "A6-301-01", "channel": "socket"}]
    assert {(s["hostname"], s["reason"]) for s in j["skipped"]} == {("A6-301-GV", "máy giảng viên"),
                                                                   ("A6-301-02", "máy đang tắt")}
    co = k.got(ag["A6-301-01"], "execute_command")[0]["command_obj"]
    assert co["action"] == "login_encrypted"
    raw = bytes.fromhex(co["data"])  # ĐÚNG cách agent giải: 12 byte nonce đầu + phần còn lại
    assert json.loads(AESGCM(bytes.fromhex(KEY)).decrypt(raw[:12], raw[12:], None)) == {"user": "SV", "pass": pw}
    # Máy báo kết quả → về người bấm, KHÔNG về người khác
    assert c.post(f"/login_result/{MAY['A6-301-01'][0]}", json={"status": "error", "msg": "Sai mật khẩu!",
                                                                "hostname": "A6-301-01"}).status_code == 200
    got = k.got(nguoi_bam, "login_response")
    assert got and got[-1]["status"] == "error" and got[-1]["hostname"] == "A6-301-01"
    assert not k.got(nguoi_khac, "login_response")


def test_dang_xuat_va_quyen(world):
    ag, devs, rooms = _dung(world)
    c, t = world["c"], tok(world)
    j = c.post("/api/remote-login/logout", json={"device_ids": [devs["A6-301-01"], devs["A6-301-02"]]},
               headers=auth(t)).get_json()
    assert j["sent"] == [{"hostname": "A6-301-01", "channel": "socket"}]
    assert j["skipped"] == [{"hostname": "A6-301-02", "reason": "máy đang tắt"}]
    assert k.got(ag["A6-301-01"], "execute_command")[0]["command"] == "logout"
    staff = tok(world, user="gv01", pw="Gv@12345")
    assert c.post("/api/remote-login/logout", json={"room_id": rooms["Phòng 301 - A6"]},
                  headers=auth(staff)).status_code == 403
    assert c.post("/api/remote-login", json={"room_id": rooms["Phòng 301 - A6"], "user": "", "password": ""},
                  headers=auth(t)).status_code == 422
