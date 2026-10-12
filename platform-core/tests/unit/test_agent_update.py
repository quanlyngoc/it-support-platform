# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Sổ tay 8.4 — Màn Quản trị → Cập nhật Agent, kiểm theo luật §0: kho bản phát hành (kiểm SHA-256), đẩy lệnh cài AN TOÀN
(updater tách rời qua Task Scheduler, tải qua Core :5443 — không bao giờ :5009, kiểm hash trước khi đụng agent), tiến độ
từng máy, bỏ qua máy đã đúng bản / đang cài dở, cài lại bản cũ (từ chối khi cổng còn mời lên bản mới), đợt lớn phải xác
nhận, All Update chỉ bật khi đủ canary + gõ xác nhận, Dừng khẩn xoá sạch cổng, phạm vi phòng, cô lập tổ chức."""

from __future__ import annotations

import hashlib
import json

import pytest
from bson import ObjectId

from app.legacy_adapter import agent_update as au
from app.legacy_adapter import contract as k
from app.legacy_adapter.releases import LoiBanPhatHanh, Releases
from app.rbac.service import create_policy
from app.tenants import service as tsvc
from tests.conftest import auth
from tests.unit.conftest import tok
from tests.unit.test_power_api import MAY, _dung

OLD, NEW = b"MZ" + b"1" * 2000, b"MZ" + b"2" * 3000


def _src(p, version: str, body: bytes):
    p.mkdir(parents=True)
    (p / "Client_Management.exe").write_bytes(body)
    (p / "manifest.json").write_text(json.dumps({"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}))
    (p / "version.txt").write_text(version)
    return p


def _kho(world, tmp_path) -> Releases:
    rel = Releases(world["ad"].root / "updates")
    rel.import_dir(_src(tmp_path / "a", "2.7.5.3", OLD))
    rel.import_dir(_src(tmp_path / "b", "2.7.5.4", NEW))
    return rel


def _ver(world, host: str, v: str) -> None:
    world["ad"].state.ingest(k.heartbeat(host, MAY[host][0], ip=MAY[host][1], client_version=v), "127.0.0.1")


def test_kho_ban_phat_hanh(world, tmp_path):
    c, t = world["c"], tok(world)
    rel = _kho(world, tmp_path)
    bad = _src(tmp_path / "c", "2.7.5.5", NEW)
    (bad / "Client_Management.exe").write_bytes(NEW + b"x")  # bộ cài lệch manifest (build dừng giữa chừng)
    with pytest.raises(LoiBanPhatHanh, match="KHÔNG khớp manifest"):
        rel.import_dir(bad)
    (bad / "manifest.json").unlink()
    with pytest.raises(LoiBanPhatHanh, match="manifest.json"):
        rel.import_dir(bad)
    j = c.get("/api/agent-update/releases", headers=auth(t)).get_json()
    assert [r["version"] for r in j["items"]] == ["2.7.5.4", "2.7.5.3"] and j["current"] is None
    assert all(r["valid"] and not r["active"] for r in j["items"])
    # chưa có bản đang phát → /download_setup 404, /check_update "không có bản mới"
    assert c.get("/download_setup").status_code == 404
    r = c.post("/api/agent-update/releases/2.7.5.4/activate", headers=auth(t))
    assert r.status_code == 200 and r.get_json()["current"]["version"] == "2.7.5.4"
    assert c.get("/check_update").get_json() == {"version": "0.0.0.0", "hash": "", "size": 0}  # cổng mặc định TẮT
    assert c.get("/download_setup").data == NEW
    assert c.get("/download_setup?ver=2.7.5.3").data == OLD  # updater "cài lại bản cũ" xin đúng bản
    assert c.get("/download_setup?ver=9.9.9").status_code == 404
    assert c.post("/api/agent-update/releases/9.9.9/activate", headers=auth(t)).status_code == 400
    assert c.post("/api/agent-update/releases/..%2F..%2Fx/activate", headers=auth(t)).status_code in (400, 404)
    assert [r["active"] for r in c.get("/api/agent-update/releases", headers=auth(t)).get_json()["items"]] == [
        True,
        False,
    ]


def test_day_cap_nhat_an_toan_va_tien_do(world, tmp_path):
    ag, devs, rooms = _dung(world)  # 301-01, 301-GV online (socket); 301-02, 405-01 tắt — đều 2.7.5.3
    c, t = world["c"], tok(world)
    _kho(world, tmp_path).activate("2.7.5.4")
    r = c.post("/api/agent-update/push", headers=auth(t), json={"device_ids": [devs["A6-301-01"], devs["A6-301-02"]]})
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["sent"] == ["A6-301-01"] and j["offline"] == ["A6-301-02"] and j["mode"] == "update"
    co = k.got(ag["A6-301-01"], "execute_command")[0]["command_obj"]
    assert co["action"] == "powershell" and co["result_token"] == j["token"] and co["timeout"] == 300
    assert "user" not in co  # không user/pass → agent chạy quyền SYSTEM (bài học 10.22)
    s = co["script"]
    assert "schtasks /create /tn PhenikaaITUpdate" in s and "/ru SYSTEM" in s  # giao Task Scheduler, không là con agent
    assert "$URLS=@('https://10.21.24.142:5443/download_setup')" in s and ":5009" not in s
    assert f"$SHA='{hashlib.sha256(NEW).hexdigest()}'" in s and f"$SIZE={len(NEW)}" in s
    assert "Get-FileHash" in s and s.index("$h -eq $SHA") < s.index("Stop-Process -Name Client_Manager")  # hash trước
    assert "GIU NGUYEN agent cu" in s and "Register-ScheduledTask -TaskName 'PhenikaaITMonitor'" in s

    # tiến độ từng máy (updater POST về /ps_bulk_result/<token>)
    def trang_thai():
        st = c.get("/api/agent-update/status", headers=auth(t)).get_json()
        return {m["hostname"]: m for m in st["machines"]}, st

    m, st = trang_thai()
    assert st["target"]["version"] == "2.7.5.4" and m["A6-301-01"]["push"]["state"] == "waiting"
    assert m["A6-301-01"]["status"] == "outdated" and m["A6-301-02"]["status"] == "offline"
    for out, state in (
        ("PUSH-OK create=0 run=0 as=nt authority\\system net: 5443=True", "running"),
        ("Download 45%", "running"),
        ("Download 100% - Update 35%", "running"),
        ("Successful", "done"),
    ):
        c.post(f"/ps_bulk_result/{j['token']}", json={"hostname": "A6-301-01", "status": "running", "stdout": out})
        p = trang_thai()[0]["A6-301-01"]["push"]
        assert p["state"] == state, (out, p)
    assert (
        c.get(f"/api/agent-update/push/{j['token']}", headers=auth(t)).get_json()["stages"]["A6-301-01"]["state"]
        == "done"
    )
    # máy báo lên bản mới → "đúng bản"; đẩy lại thì BỎ QUA (mỗi lần cài là một lần dừng agent)
    _ver(world, "A6-301-01", "2.7.5.4")
    m, st = trang_thai()
    assert m["A6-301-01"]["status"] == "uptodate" and st["summary"]["uptodate"] == 1
    # đang cài dở → không đẩy chồng
    j2 = c.post("/api/agent-update/push", headers=auth(t), json={"device_ids": [devs["A6-301-GV"]]}).get_json()
    assert j2["sent"] == ["A6-301-GV"]
    j3 = c.post("/api/agent-update/push", headers=auth(t), json={"room_ids": [rooms["Phòng 301 - A6"]]}).get_json()
    assert j3["sent"] == [] and j3["busy"] == ["A6-301-GV"] and j3["skipped_uptodate"] == ["A6-301-01"]
    assert j3["offline"] == ["A6-301-02"]
    c.post(
        f"/ps_bulk_result/{j2['token']}",
        json={"hostname": "A6-301-GV", "status": "error", "stdout": "Unsuccessful: tai that bai - timeout"},
    )
    m, st = trang_thai()
    assert m["A6-301-GV"]["push"]["state"] == "error" and "tai that bai" in m["A6-301-GV"]["push"]["text"]
    assert st["summary"]["failed"] == 1
    assert c.post("/api/agent-update/push", headers=auth(t), json={}).status_code == 400
    assert c.get("/api/agent-update/push/khongco", headers=auth(t)).status_code == 404


def test_cai_lai_ban_cu_va_dot_lon(world, tmp_path, monkeypatch):
    ag, devs, _ = _dung(world)
    c, t = world["c"], tok(world)
    _kho(world, tmp_path).activate("2.7.5.4")
    _ver(world, "A6-301-01", "2.7.5.4")
    # cổng đang mời máy này lên 2.7.5.4 → hạ xuống bản cũ bị từ chối (máy sẽ tự lên lại)
    c.put("/api/legacy/update_gate", headers=auth(t), json={"hosts": ["A6-301-01"]})
    r = c.post(
        "/api/agent-update/push", headers=auth(t), json={"device_ids": [devs["A6-301-01"]], "version": "2.7.5.3"}
    )
    assert r.status_code == 409 and r.get_json()["hosts"] == ["A6-301-01"]
    c.put("/api/agent-update/all", headers=auth(t), json={"on": False})  # Dừng khẩn = cổng trống
    r = c.post(
        "/api/agent-update/push", headers=auth(t), json={"device_ids": [devs["A6-301-01"]], "version": "2.7.5.3"}
    )
    j = r.get_json()
    assert r.status_code == 200 and j["mode"] == "reinstall" and j["sent"] == ["A6-301-01"]
    s = k.got(ag["A6-301-01"], "execute_command")[-1]["command_obj"]["script"]
    assert "/download_setup?ver=2.7.5.3')" in s and hashlib.sha256(OLD).hexdigest() in s
    assert (
        c.post(
            "/api/agent-update/push", headers=auth(t), json={"device_ids": [devs["A6-301-01"]], "version": "1.0.0"}
        ).status_code
        == 404
    )
    # cài lại ĐÚNG bản đang phát (sửa máy hỏng) — không bỏ qua dù đã đúng bản
    c.post(f"/ps_bulk_result/{j['token']}", json={"hostname": "A6-301-01", "stdout": "Successful"})
    j = c.post(
        "/api/agent-update/push", headers=auth(t), json={"device_ids": [devs["A6-301-01"]], "version": "2.7.5.4"}
    ).get_json()
    assert j["sent"] == ["A6-301-01"] and j["mode"] == "reinstall"
    # đợt lớn hơn MANY máy phải xác nhận lại
    monkeypatch.setattr(au, "MANY", 0)
    r = c.post("/api/agent-update/push", headers=auth(t), json={"device_ids": [devs["A6-301-GV"]]})
    assert r.status_code == 409 and r.get_json()["need_confirm"] is True
    r = c.post(
        "/api/agent-update/push", headers=auth(t), json={"device_ids": [devs["A6-301-GV"]], "confirm_many": True}
    )
    assert r.status_code == 200 and r.get_json()["sent"] == ["A6-301-GV"]
    with pytest.raises(ValueError):
        au.updater_script("abc'; rm", "https://x", "1.0", "ab", 1)  # chống chèn vào script PowerShell


def test_all_update_canary_va_dung_khan(world, tmp_path):
    _, devs, _ = _dung(world)
    c, t = world["c"], tok(world)
    _kho(world, tmp_path).activate("2.7.5.4")
    assert c.put("/api/agent-update/all", headers=auth(t), json={"on": True, "confirm": "ok"}).status_code == 400
    r = c.put("/api/agent-update/all", headers=auth(t), json={"on": True, "confirm": "BẬT"})
    assert r.status_code == 409 and "canary" in r.get_json()["message"]  # chưa máy nào chạy bản mới
    _ver(world, "A6-301-01", "2.7.5.4")
    assert c.put("/api/agent-update/all", headers=auth(t), json={"on": True, "confirm": "bật"}).status_code == 409
    _ver(world, "A6-301-GV", "2.7.5.4")
    r = c.put("/api/agent-update/all", headers=auth(t), json={"on": True, "confirm": "bật"})
    assert r.status_code == 200 and r.get_json()["gate"]["all"] is True
    assert c.get("/check_update").get_json()["version"] == "2.7.5.4"  # mọi máy được mời (agent tự cài tách rời)
    # đang All Update thì không đổi bản đang phát (= đẩy bản chưa canary cho cả trường)
    assert c.post("/api/agent-update/releases/2.7.5.3/activate", headers=auth(t)).status_code == 409
    c.put(
        "/api/legacy/update_gate",
        headers=auth(t),
        json={"all": True, "hosts": ["X"], "rollout_rooms": ["405"], "rollout_percent": 30},
    )
    r = c.put("/api/agent-update/all", headers=auth(t), json={"on": False})  # DỪNG KHẨN
    assert r.get_json()["gate"] == {"all": False, "hosts": [], "rollout_rooms": [], "rollout_percent": 0}
    assert c.get("/check_update").get_json()["version"] == "0.0.0.0"
    st = c.get("/api/agent-update/status", headers=auth(t)).get_json()
    assert st["can_global"] and not any(m["invited"] for m in st["machines"])


def test_quyen_va_pham_vi(world, tmp_path):
    _, devs, rooms = _dung(world)
    c, t = world["c"], tok(world)
    _kho(world, tmp_path).activate("2.7.5.4")
    tid = world["tid"]
    p_view = create_policy(db := world["ad"].db, tid, "Xem", permission_codes=["device.control"])["_id"]
    tsvc.create_user(db, tid, "nv", password="Nv@12345", policy_ids=[p_view])
    hn = auth(tok(world, user="nv", pw="Nv@12345"))
    assert c.get("/api/agent-update/status", headers=hn).status_code == 403
    p301 = create_policy(
        db, tid, "IT 301", permission_codes=["agent.update"], room_ids=[ObjectId(rooms["Phòng 301 - A6"])]
    )["_id"]
    tsvc.create_user(db, tid, "it301", password="It@12345", policy_ids=[p301])
    hi = auth(tok(world, user="it301", pw="It@12345"))
    st = c.get("/api/agent-update/status", headers=hi).get_json()
    assert {m["hostname"] for m in st["machines"]} == {"A6-301-01", "A6-301-02", "A6-301-GV"} and not st["can_global"]
    assert c.post("/api/agent-update/push", headers=hi, json={"device_ids": [devs["A6-405-01"]]}).status_code == 404
    assert c.post("/api/agent-update/push", headers=hi, json={"device_ids": [devs["A6-301-01"]]}).status_code == 200
    assert c.put("/api/agent-update/all", headers=hi, json={"on": False}).status_code == 403
    assert c.post("/api/agent-update/releases/2.7.5.3/activate", headers=hi).status_code == 403
    assert c.get("/api/agent-update/status", headers=auth(tok(world, tenant="BBB"))).status_code == 404
    assert c.get("/api/agent-update/status").status_code == 401
    assert t
