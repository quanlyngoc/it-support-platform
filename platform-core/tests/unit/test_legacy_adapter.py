# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Bộ tương thích agent v2 — các luật sống còn A1–A10 và hành vi ngoài phạm vi fixture hợp đồng."""
from __future__ import annotations

import dataclasses
import time

import pytest

from app.legacy_adapter import contract as k
from app.legacy_adapter.identity import mac12, room_from_hostname_raw, valid_serial
from app.legacy_adapter.state import QUEUE_TTL
from app.legacy_adapter.update_gate import CLOSED
from app.server import create_app
from app.tenants.repo import repo_for
from tests.conftest import TEST_SETTINGS, _make_tenant, auth, fake_ldap
from tests.unit.conftest import tok as _tok


# ====================================================================== định danh
def test_identity_loc_rac_va_suy_phong():
    assert not valid_serial("N/A") and not valid_serial("...") and not valid_serial("1234") and valid_serial("ABC1234")
    assert mac12("AA-BB-CC-00-30-01") == "aabbcc003001" and mac12("xx") == ""
    assert room_from_hostname_raw("A6-405-12") == "Phòng 405 - A6"
    assert room_from_hostname_raw("DESKTOP-ABC") == "Phòng chờ"
    assert room_from_hostname_raw("KTX-01") == "Khu vực KTX"


# ====================================================================== A1 / A3
def test_a1_update_loi_noi_bo_van_200(world, monkeypatch):
    def hong(*_a, **_k):
        raise RuntimeError("lỗi giả")

    monkeypatch.setattr(world["ad"].state, "ingest", hong)
    r = world["c"].post("/update", json=k.heartbeat())
    assert r.status_code == 200 and r.get_json() == {"status": "success"}


def test_a1_ip_ngoai_dai_van_200_nhung_khong_nhan(db, tmp_path):
    _make_tenant(db, "PHENIKAA")
    s = dataclasses.replace(TEST_SETTINGS, DATA_DIR=str(tmp_path), LEGACY_ALLOWED_CIDRS=("10.0.0.0/8",))
    a = create_app(db=db, settings=s, async_mode="threading", ldap_bind=fake_ldap)
    c = a.test_client()
    r = c.post("/update", json=k.heartbeat(), environ_base={"REMOTE_ADDR": "192.168.1.5"})
    assert r.status_code == 200 and not a.extensions["legacy"].state.hosts
    assert c.get("/check_command/aa:bb:cc:00:30:01", environ_base={"REMOTE_ADDR": "192.168.1.5"}).status_code == 403
    r = c.post("/update", json=k.heartbeat(), environ_base={"REMOTE_ADDR": "10.21.30.101"})
    assert r.get_json()["action"] == "reconnect_socket" and "A6-301-01" in a.extensions["legacy"].state.hosts


def test_a3_reconnect_socket_roi_het_khi_da_register(world):
    c = world["c"]
    assert c.post("/update", json=k.heartbeat()).get_json() == {"status": "success", "action": "reconnect_socket"}
    k.agent(world["app"])
    assert c.post("/update", json=k.heartbeat()).get_json() == {"status": "success"}


# ====================================================================== A8: gửi lệnh
def test_a8_kenh_lenh_socket_http_none(world):
    ad, c = world["ad"], world["c"]
    assert ad.dispatch("A6-301-01", "", {"command": "logout"})["channel"] == "none"  # máy chưa từng thấy
    c.post("/update", json=k.heartbeat())
    r = ad.dispatch("A6-301-01", "", {"command_obj": {"action": "powershell", "script": "hostname"}})
    assert r["channel"] == "http"
    got = c.get("/check_command/AA:BB:CC:00:30:01").get_json()["command_obj"]  # MAC hoa vẫn khớp
    assert got["command_id"] == r["command_id"] and got["script"] == "hostname"
    assert c.get("/check_command/aa:bb:cc:00:30:01").get_json() == {"command": None}  # lấy rồi là hết


def test_a8_hang_doi_http_fifo_va_het_han(world):
    ad, c, clock = world["ad"], world["c"], world["clock"]
    c.post("/update", json=k.heartbeat())
    ad.dispatch("A6-301-01", "", {"command": "logout"})
    ad.dispatch("A6-301-01", "", {"command": "restart"})
    assert c.get("/check_command/aa:bb:cc:00:30:01").get_json() == {"command": "logout"}
    clock[0] += QUEUE_TTL + 1  # máy bật lại sau 5' không được chạy lệnh cũ
    assert c.get("/check_command/aa:bb:cc:00:30:01").get_json() == {"command": None}


def test_lenh_tat_qua_http_danh_offline_va_ghi_moc_tat_sach(world):
    ad, c = world["ad"], world["c"]
    c.post("/update", json=k.heartbeat())
    ad.dispatch("A6-301-01", "", {"command": "shutdown"})
    assert ad.tat_sach_since("a6-301-01") is not None
    assert c.get("/check_command/aa:bb:cc:00:30:01").get_json() == {"command": "shutdown"}
    assert not ad.state.is_online("A6-301-01")


def test_ack_bo_cuoc_khi_mat_socket_khong_chuyen_http(world):
    ad, clock = world["ad"], world["clock"]
    ag = k.agent(world["app"])
    r = ad.dispatch("A6-301-01", "", {"command": "logout"})
    ag.disconnect()
    clock[0] += 9
    ad.retry_tick()
    assert ad.state.ack_failed[r["command_id"]]["reason"] == "mat_socket"
    assert not ad.state.queue  # KHÔNG tự đẩy sang /check_command (đường HTTP của agent không chống chạy đúp)


def test_reply_sid_la_socket_agent_thi_khong_chuyen(world):
    app = world["app"]
    a1, a2 = k.agent(app), k.agent(app, k.OTHER_HOST, k.OTHER_MAC)
    a2.get_received()
    a1.emit("vnc_thumb", {"hostname": "A6-301-01", "image": "x", "reply_sid": k.sid_of(a2)})
    assert not k.got(a2, "vnc_thumb")


# ====================================================================== bộ ghi computers (A10)
def _computers(w):
    return {d["legacy_hostname"]: d for d in repo_for(w["app"].extensions["itm_db"], w["tid"], "computers").find()}


def test_ghi_computers_gop_va_khong_de_gia_tri_tam(world):
    ad, c, clock = world["ad"], world["c"], world["clock"]
    c.post("/update", json=k.heartbeat())
    ad.writer_tick()
    d = _computers(world)["A6-301-01"]
    assert d["is_online"] and d["serial"] == "ABC1234" and d["source"] == "agent_v2"
    assert d["room_name"] == "Phòng 301 - A6"
    boot = k.heartbeat(cpu="N/A", serial="N/A", model="N/A", ram="N/A")
    c.post("/update", json=boot)
    clock[0] += 61
    c.post("/update", json=boot)
    assert ad.writer_tick() == 1
    d = _computers(world)["A6-301-01"]
    assert (d["serial"], d["model"], d["cpu"]) == ("ABC1234", "OptiPlex 7080", "Intel(R) Core(TM) i5-10500")
    assert ad.writer_tick() == 0  # không đổi trạng thái, chưa đủ 60 s → không ghi


def test_mat_nhip_tim_35s_thi_offline_khong_xoa_may(world):
    ad, c, clock = world["ad"], world["c"], world["clock"]
    c.post("/update", json=k.heartbeat())
    ad.writer_tick()
    clock[0] += 36
    ad.writer_tick()
    d = _computers(world)["A6-301-01"]
    assert d["is_online"] is False and d["offline_reason"] == "mat_nhip_tim"


def test_trao_phan_cung_ghi_su_kien_va_luu_tru_khong_xoa(world):
    ad, c, clock = world["ad"], world["c"], world["clock"]
    db = world["app"].extensions["itm_db"]
    c.post("/update", json=k.heartbeat("A6-404-11", "aa:bb:cc:00:40:11", serial="DELL404"))
    ad.writer_tick()
    clock[0] += 120  # máy 404-11 tắt đã lâu
    ad.writer_tick()
    c.post("/update", json=k.heartbeat("A6-501-03", "aa:bb:cc:00:40:11", serial="DELL404"))  # ổ cứng 501-03 lắp vào
    ad.writer_tick()
    ev = list(repo_for(db, world["tid"], "machine_events").find({"event": "trao_phan_cung"}))
    assert len(ev) == 1 and ev[0]["hostname"] == "A6-501-03" and ev[0]["other_host"] == "A6-404-11"
    assert ev[0]["matched_by"] == "MAC" and ev[0]["action"] == "giu_nguyen"
    arch = list(repo_for(db, world["tid"], "computers_archive").find())
    assert len(arch) == 1 and arch[0]["legacy_hostname"] == "A6-404-11"
    assert set(_computers(world)) == {"A6-404-11", "A6-501-03"}  # GIỮ NGUYÊN cả hai dòng
    clock[0] += 61
    c.post("/update", json=k.heartbeat("A6-501-03", "aa:bb:cc:00:40:11", serial="DELL404"))
    ad.writer_tick()
    assert repo_for(db, world["tid"], "machine_events").count({"event": "trao_phan_cung"}) == 1  # chống ghi lặp 6 h


def test_anti_ghost_hai_may_cung_bat_khong_ghi_su_kien(world):
    ad, c = world["ad"], world["c"]
    db = world["app"].extensions["itm_db"]
    c.post("/update", json=k.heartbeat("A6-301-01", "aa:bb:cc:00:30:01", serial="GENERIC1"))
    c.post("/update", json=k.heartbeat("A6-301-02", "aa:bb:cc:00:30:02", serial="GENERIC1"))
    ad.writer_tick()
    ad.writer_tick()
    assert repo_for(db, world["tid"], "machine_events").count({}) == 0


def test_cung_ten_doi_serial_va_mac(world):
    ad, c, clock = world["ad"], world["c"], world["clock"]
    db = world["app"].extensions["itm_db"]
    c.post("/update", json=k.heartbeat(serial="OLD1234"))
    ad.writer_tick()
    clock[0] += 61
    c.post("/update", json=k.heartbeat(mac="aa:bb:cc:99:99:99", serial="NEW5678"))
    ad.writer_tick()
    evs = {e["event"]: e for e in repo_for(db, world["tid"], "machine_events").find()}
    assert evs["doi_serial"]["old_value"] == "OLD1234" and evs["doi_serial"]["new_value"] == "NEW5678"
    assert evs["doi_mac"]["new_value"] == "aabbcc999999"


def test_phut_su_dung_cong_moi_60s(world):
    ad, c, clock = world["ad"], world["c"], world["clock"]
    db = world["app"].extensions["itm_db"]
    c.post("/update", json=k.heartbeat())
    ad.writer_tick()
    for _ in range(2):
        clock[0] += 61
        c.post("/update", json=k.heartbeat())
        ad.writer_tick()
    rows = list(repo_for(db, world["tid"], "usage_stats").find())
    assert len(rows) == 1 and rows[0]["online_minutes"] == 2 and rows[0]["room_name"] == "Phòng 301 - A6"


# ====================================================================== cổng cập nhật (A4/A5)
def test_cong_cap_nhat_mac_dinh_dong_va_bo_cai_lech_manifest(world):
    ad, c = world["ad"], world["c"]
    k.write_installer(ad, "2.7.5.4")
    assert c.get("/check_update").get_json() == CLOSED  # có bộ cài nhưng cổng tắt
    repo_for(ad.db, world["tid"], "settings").update_one({"key": "update.all"}, {"$set": {"value": True}}, upsert=True)
    ad.gate.invalidate()
    assert c.get("/check_update").get_json()["version"] == "2.7.5.4"
    (ad.root / "updates" / "Client_Management.exe").write_bytes(b"hong")  # build dừng giữa chừng
    ad.gate.invalidate()
    assert c.get("/check_update").get_json() == CLOSED
    assert c.get("/download_setup").status_code == 404


@pytest.mark.parametrize("gate,open_", [({"update.hosts": ["a6-301-01"]}, True),
                                        ({"update.rollout_rooms": ["Phòng 301 - A6"]}, True),
                                        ({"update.rollout_rooms": ["405"]}, False),
                                        ({"update.rollout_percent": 100}, True),
                                        ({"update.rollout_percent": 0}, False)])
def test_cong_chia_dot(world, gate, open_):
    ad, c = world["ad"], world["c"]
    k.write_installer(ad, "2.7.5.4")
    c.post("/update", json=k.heartbeat())  # Core biết IP 127.0.0.1 là máy A6-301-01
    for key, val in gate.items():
        repo_for(ad.db, world["tid"], "settings").update_one({"key": key}, {"$set": {"value": val}}, upsert=True)
    ad.gate.invalidate()
    assert (c.get("/check_update").get_json()["version"] == "2.7.5.4") is open_


def test_tai_bo_cai_qua_tai_tra_503(world):
    ad, c = world["ad"], world["c"]
    k.write_installer(ad, "2.7.5.4")
    codes = [c.get("/download_setup").status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 503
    world["clock"][0] += 46  # slot tự hết hạn → không kẹt 503
    assert c.get("/download_setup").status_code == 200


# ====================================================================== API Desktop / người vận hành
def test_api_online_lenh_va_co_lap_to_chuc(world):
    c, app = world["c"], world["app"]
    ag = k.agent(app)
    tp, tb = _tok(world), _tok(world, "BBB")
    j = c.get("/api/legacy/online", headers=auth(tp)).get_json()
    assert j["total_online"] == 1 and j["hosts"][0]["channel"] == "socket"
    assert c.get("/api/legacy/online", headers=auth(tb)).status_code == 404  # tổ chức khác không thấy
    r = c.post("/api/legacy/command", json={"hostname": "A6-301-01", "command": "logout"}, headers=auth(tb))
    assert r.status_code == 404 and not k.got(ag, "execute_command")
    r = c.post("/api/legacy/command", json={"hostname": "A6-301-01", "command": "logout"}, headers=auth(tp))
    assert r.status_code == 200 and r.get_json()["channel"] == "socket" and k.got(ag, "execute_command")
    r = c.post("/api/legacy/command", json={"hostname": "A6-999-99", "command": "logout"}, headers=auth(tp))
    assert r.status_code == 409
    r = c.post("/api/legacy/command", json={"hostname": "A6-301-01"}, headers=auth(tp))
    assert r.status_code == 422


def test_api_powershell_ket_qua_luu_csdl_va_poll(world):
    c, app = world["c"], world["app"]
    ag = k.agent(app)
    tp = _tok(world)
    r = c.post("/api/legacy/powershell", json={"hostnames": ["a6-301-01", "A6-301-77"], "script": "whoami"},
               headers=auth(tp)).get_json()
    assert r["total"] == 2 and r["channels"] == {"A6-301-01": "socket", "A6-301-77": "none"}
    cmd = k.got(ag, "execute_command")[0]["command_obj"]
    assert cmd["result_token"] == r["token"] and cmd["user"] == "" and cmd["script"] == "whoami"
    c.post(f"/ps_bulk_result/{r['token']}", json={"hostname": "A6-301-01", "status": "done", "exit_code": 0,
                                                   "stdout": "nt authority\\system", "stderr": ""})
    res = c.get(f"/api/legacy/results/{r['token']}", headers=auth(tp)).get_json()
    assert res["done"] == 1 and res["results"][0]["stdout"] == "nt authority\\system"
    assert c.get(f"/api/legacy/results/{r['token']}", headers=auth(_tok(world, "BBB"))).status_code == 404


def test_api_cong_cap_nhat_can_quyen(world):
    c = world["c"]
    staff = _tok(world, user="gv01", pw="Gv@12345")
    assert c.put("/api/legacy/update_gate", json={"all": True}, headers=auth(staff)).status_code == 403
    tp = _tok(world)
    j = c.put("/api/legacy/update_gate", json={"hosts": ["a6-301-01"], "rollout_percent": 5}, headers=auth(tp))
    assert j.status_code == 200 and j.get_json()["hosts"] == ["A6-301-01"] and j.get_json()["manifest"] is None


# ====================================================================== thay đổi phần cứng → sự cố
@pytest.mark.parametrize("cu,moi,tieu_de", [
    ("16GB (2 thanh: 8GB [SN:A1], 8GB [SN:A2])", "24GB (3 thanh)", "THÊM RAM"),
    ("16GB (2 thanh: 8GB [SN:A1], 8GB [SN:A2])", "8GB (1 thanh: 8GB [SN:A1])", "MẤT RAM"),
    ("16GB (2 thanh: 8GB [SN:A1], 8GB [SN:A2])", "16GB (2 thanh: 8GB [SN:A1], 8GB [SN:B9])", "TRÁO ĐỔI RAM"),
    ("16GB (2 thanh: 8GB [SN:A1], 8GB [SN:A2])", "16GB (2 thanh: 8GB [SN:A1], 8GB [SN:A2])", None),
    ("16GB [SN:00000000]", "16GB [SN:A1]", None),  # SN chứa "0000" là rác → không coi là tráo
    ("16GB", "N/A", None), ("N/A", "8GB", None),    # giá trị tạm lúc khởi động → không so
])
def test_phat_hien_doi_ram(cu, moi, tieu_de):
    from app.legacy_adapter.hardware import ram_doi

    td = ram_doi(cu, moi)
    assert (td.tieu_de if td else None) == tieu_de


def test_phat_hien_doi_o_cung():
    from app.legacy_adapter.hardware import disk_doi

    assert disk_doi("SSD (256GB) [SN:X1]", "SSD (256GB) [SN:X1] · HDD (1000GB)").tieu_de == "THÊM Ổ CỨNG"
    assert disk_doi("SSD (256GB) [SN:X1]", "SSD (256GB) [SN:Y7]").tieu_de == "TRÁO ĐỔI Ổ CỨNG"
    assert disk_doi("SSD (256GB)", "N/A") is None


def _incidents(w):
    return list(repo_for(w["app"].extensions["itm_db"], w["tid"], "incidents").find({}, {"_id": 0, "tenant_id": 0}))


def test_doi_ram_tao_mot_su_co_va_phat_realtime(world):
    ad, c, clock = world["ad"], world["c"], world["clock"]
    ram8 = "8GB (1 thanh: 8GB Bus2666 [SN:A1])"
    c.post("/update", json=k.heartbeat(ram="N/A"))  # khởi động: giá trị tạm
    ad.writer_tick()
    clock[0] += 61
    c.post("/update", json=k.heartbeat(ram=ram8))
    ad.writer_tick()
    assert _incidents(world) == []  # N/A → 8GB là agent nạp xong phần cứng, KHÔNG phải đổi RAM
    nhan = []
    ad.writer().on_incident = nhan.append
    for _ in range(2):  # đổi RAM, rồi nhịp sau vẫn 4GB → chỉ 1 sự cố (đang chờ thì không tạo trùng)
        clock[0] += 61
        c.post("/update", json=k.heartbeat(ram="4GB (1 thanh: 4GB [SN:Z9])"))
        ad.writer_tick()
    inc = _incidents(world)
    assert len(inc) == 1 and inc[0]["title"] == "MẤT RAM" and inc[0]["status"] == "PENDING"
    assert inc[0]["category"] == "hardware_ram" and inc[0]["source"] == "SYSTEM_WATCHDOG"
    assert inc[0]["room_name"] == "Phòng 301 - A6" and inc[0]["device_id"] is not None
    assert len(nhan) == 1 and nhan[0]["title"] == "MẤT RAM"


def test_het_pin_cmos_chi_bao_luc_chuyen_trang_thai(world):
    ad, c, clock = world["ad"], world["c"], world["clock"]
    for _ in range(3):
        c.post("/update", json=k.heartbeat(cmos_battery="Hết pin (3 lần reset giờ)"))
        ad.writer_tick()
        clock[0] += 61
    assert [i["title"] for i in _incidents(world)] == ["HẾT PIN CMOS"]


def test_doi_ram_luc_core_tat_van_bat_duoc(world, db):
    """Giá trị cũ nạp từ CSDL lúc khởi động (prime): đổi RAM trong lúc Core tắt vẫn bị phát hiện."""
    repo_for(db, world["tid"], "computers").insert_one({"hostname": "A6-301-01", "legacy_hostname": "A6-301-01",
                                                        "ram": "16GB (2 thanh)", "disk": "SSD (256GB)"})
    world["c"].post("/update", json=k.heartbeat(ram="8GB (1 thanh)", disk="SSD (256GB)"))
    world["ad"].writer_tick()
    assert [i["title"] for i in _incidents(world)] == ["MẤT RAM"]


# ====================================================================== dọn tệp cũ
def test_don_tep_cu_chi_xoa_ma_phien_qua_han(tmp_path):
    import os

    from app.legacy_adapter.cleanup import don_tep_cu

    now = time.time()
    cu, moi = now - 200 * 3600, now - 3600

    def tao(rel, mtime, thu_muc=False):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if thu_muc:
            p.mkdir()
        else:
            p.write_text("x")
        os.utime(p, (mtime, mtime))
        return p

    giu = [tao("work/ba7c4000000000000000000000000002", moi, True),          # còn hạn
           tao("work/Ca sang", cu, True),                                    # không phải mã phiên → giữ
           tao("collect/c0ec7000000000000000000000000002", now - 100 * 3600, True),  # collect giữ 168 giờ
           tao("updates/Client_Management.exe", cu)]                         # bộ cài: không bao giờ dọn
    xoa = [tao("work/ba7c4000000000000000000000000001", cu, True),
           tao("collect/c0ec7000000000000000000000000001", cu, True),
           tao("fs_tmp/f5000000000000000000000000000001_bai.zip", cu)]
    assert don_tep_cu(tmp_path, now) == {"work": 1, "collect": 1, "fs_tmp": 1}
    assert all(p.exists() for p in giu) and not any(p.exists() for p in xoa)
