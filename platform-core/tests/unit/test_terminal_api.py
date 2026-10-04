# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Sổ tay 6.4: PowerShell hàng loạt (quyền SYSTEM, phiên có TRƯỚC khi gửi lệnh, quá hạn → timeout, lọc phạm vi) và
terminal ConPTY (chỉ mở sau khi CHÍNH người đó vừa xác thực đúng, dùng một lần)."""
from __future__ import annotations

from datetime import datetime, timedelta

from bson import ObjectId

from app.control import bulk
from app.legacy_adapter import contract as k
from app.rbac.service import create_policy
from app.realtime.hub import DESKTOP_NS
from app.tenants import service as tsvc
from tests.conftest import auth
from tests.unit.conftest import tok
from tests.unit.test_power_api import MAY, _dung


def test_chay_hang_loat_quyen_system_va_ket_qua(world):
    ag, _, rooms = _dung(world)
    c, t = world["c"], tok(world)
    ad = world["ad"]
    goc = ad.dispatch
    phien_luc_gui = []

    def dispatch(host, mac, payload, **kw):  # agent nhanh có thể báo kết quả NGAY → phiên phải có sẵn lúc này
        tk = (payload.get("command_obj") or {}).get("result_token")
        phien_luc_gui.append(ad.store().session("ps_bulk", tk) is not None)
        return goc(host, mac, payload, **kw)

    ad.dispatch = dispatch
    r = c.post("/api/terminal/bulk", json={"room_id": rooms["Phòng 301 - A6"], "script": "hostname; whoami"},
               headers=auth(t))
    ad.dispatch = goc
    j = r.get_json()
    assert r.status_code == 200 and j["total"] == 1 and j["deadline_s"] == 135 and phien_luc_gui == [True]
    assert {(s["hostname"], s["reason"]) for s in j["skipped"]} == {("A6-301-GV", "máy giảng viên"),
                                                                   ("A6-301-02", "máy đang tắt")}
    co = k.got(ag["A6-301-01"], "execute_command")[0]["command_obj"]
    assert co == {"action": "powershell", "script": "hostname; whoami", "user": "", "pass": "",  # SYSTEM (10.22)
                  "result_token": j["token"], "timeout": 90}
    st = c.get(f"/api/terminal/bulk/{j['token']}", headers=auth(t)).get_json()
    assert st["complete"] is False and st["results"] == [{"hostname": "A6-301-01", "status": "running"}]
    d = k.browser(world["app"], t)
    assert d.emit("subscribe_result", {"token": j["token"]}, namespace=DESKTOP_NS, callback=True)["ok"]
    d.get_received(DESKTOP_NS)
    kq = {"hostname": "A6-301-01", "status": "done", "exit_code": 0, "stdout": "A6-301-01\nnt authority\\system"}
    assert c.post(f"/ps_bulk_result/{j['token']}", json=kq).status_code == 200
    assert k.got(d, "ps_bulk_result")[0]["result"]["stdout"].endswith("nt authority\\system")
    st = c.get(f"/api/terminal/bulk/{j['token']}", headers=auth(t)).get_json()
    assert st["complete"] is True and st["results"][0]["status"] == "done" and st["results"][0]["exit_code"] == 0
    assert c.get("/api/terminal/bulk/khongco", headers=auth(t)).status_code == 404


def test_qua_han_thi_danh_dau_timeout(world):
    _, devs, _ = _dung(world)
    j = world["c"].post("/api/terminal/bulk", json={"device_ids": [devs["A6-301-01"]], "script": "sleep 999",
                                                    "timeout": 5}, headers=auth(tok(world))).get_json()
    st = bulk.status(world["ad"], j["token"])
    started = datetime.fromisoformat(st["started_at"])
    assert bulk.status(world["ad"], j["token"], started + timedelta(seconds=49))["results"][0]["status"] == "running"
    late = bulk.status(world["ad"], j["token"], started + timedelta(seconds=51))
    assert late["results"][0]["status"] == "timeout" and late["complete"] is True


def test_gioi_han_phong_va_api_cu(world, db):
    _, devs, rooms = _dung(world)
    c, t = world["c"], tok(world)
    pid = create_policy(db, world["tid"], "GS 301", permission_codes=["device.control"],
                        room_ids=[ObjectId(rooms["Phòng 301 - A6"])])["_id"]
    tsvc.create_user(db, world["tid"], "gs301", password="Gs@12345", policy_ids=[pid])
    g = tok(world, user="gs301", pw="Gs@12345")
    cua_admin = c.post("/api/terminal/bulk", json={"device_ids": [devs["A6-405-01"]], "script": "x"},
                       headers=auth(t)).get_json()["token"]
    assert c.get(f"/api/terminal/bulk/{cua_admin}", headers=auth(g)).status_code == 404  # lượt của người khác
    j = c.post("/api/terminal/bulk", json={"device_ids": [devs["A6-405-01"], devs["A6-301-01"]], "script": "x"},
               headers=auth(g)).get_json()
    assert [s["hostname"] for s in j["sent"]] == ["A6-301-01"]  # máy phòng 405 ngoài phạm vi → bỏ qua
    assert c.get(f"/api/terminal/bulk/{j['token']}", headers=auth(g)).status_code == 200
    assert c.post("/api/legacy/command", json={"hostname": "A6-405-01", "command": "shutdown"},
                  headers=auth(g)).status_code == 403  # API thô không lọc phạm vi → khoá với tài khoản giới hạn
    assert c.post("/api/legacy/powershell", json={"hostnames": ["A6-405-01"], "script": "x"},
                  headers=auth(g)).status_code == 403


def test_terminal_chi_mo_sau_khi_xac_thuc_dung(world):
    ag, devs, _ = _dung(world)
    c, t = world["c"], tok(world)
    did, mac = devs["A6-301-01"], MAY["A6-301-01"][0]
    d = k.browser(world["app"], t)
    assert d.emit("watch_device", {"device_id": did, "kind": "pty"}, namespace=DESKTOP_NS, callback=True)["ok"]
    d.get_received(DESKTOP_NS)
    assert c.post(f"/api/devices/{did}/terminal/start", json={}, headers=auth(t)).status_code == 403  # chưa xác thực
    r = c.post(f"/api/devices/{did}/terminal/validate", json={"user": "SV", "password": "x"}, headers=auth(t))
    assert r.status_code == 200
    assert k.got(ag["A6-301-01"], "execute_command")[0]["command_obj"] == {"action": "pty_validate", "user": "SV",
                                                                          "pass": "x"}
    c.post(f"/pty_auth_result/{mac}", json={"status": "error", "msg": "Sai tài khoản hoặc mật khẩu!"})
    assert k.got(d, "pty_auth_response")[0]["status"] == "error"
    assert c.post(f"/api/devices/{did}/terminal/start", json={}, headers=auth(t)).status_code == 403  # sai → không mở
    # Xác thực đúng → mở được ĐÚNG MỘT lần, đúng người
    c.post(f"/api/devices/{did}/terminal/validate", json={"user": "SV", "password": "dung"}, headers=auth(t))
    c.post(f"/pty_auth_result/{mac}", json={"status": "success"})
    tsvc.create_user(world["app"].extensions["itm_db"], world["tid"], "it02", password="It@12345",
                     policy_ids=[world["t"]["P"]["super_pid"]])
    khac = tok(world, user="it02", pw="It@12345")
    assert c.post(f"/api/devices/{did}/terminal/start", json={}, headers=auth(khac)).status_code == 403
    ag["A6-301-01"].get_received()
    r = c.post(f"/api/devices/{did}/terminal/start", json={"cols": 140, "rows": 40}, headers=auth(t))
    assert r.status_code == 200
    assert k.got(ag["A6-301-01"], "execute_command")[0]["command_obj"] == {"action": "start_pty", "cols": 140,
                                                                          "rows": 40}
    assert c.post(f"/api/devices/{did}/terminal/start", json={}, headers=auth(t)).status_code == 403  # dùng 1 lần
    ag["A6-301-01"].emit("client_pty_output", {"mac": mac, "data": "PS C:\\> "})
    assert k.got(d, "pty_output") == [{"mac": mac, "data": "PS C:\\> "}]
    assert c.post(f"/api/devices/{did}/terminal/stop", headers=auth(t)).status_code == 200
    assert k.got(ag["A6-301-01"], "execute_command")[-1]["command_obj"] == {"action": "stop_pty"}
    staff = tok(world, user="gv01", pw="Gv@12345")
    assert c.post(f"/api/devices/{did}/terminal/validate", json={"user": "a", "password": "b"},
                  headers=auth(staff)).status_code == 403
