"""Test script vận hành platform-deployment/ops (Sổ tay 0.6 sao lưu, 0.7 cảnh báo online) — chạy trên dữ liệu giả."""
from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))

import canh_bao_online as cb  # noqa: E402
import sao_luu_csdl_cu as sl  # noqa: E402


# ====================================================================== 0.6 sao lưu
def _db_cu(p: pathlib.Path, n: int = 5) -> None:
    c = sqlite3.connect(p)
    c.execute("pragma journal_mode=wal")
    c.execute("create table computers (hostname text, mac text, serial text, room text, ip text, client_version text)")
    c.executemany("insert into computers values (?,?,?,?,?,?)",
                  [(f"A6-301-{i:02d}", f"aa:{i:02d}", f"SN{i}", "Phòng 301 - A6", f"10.0.0.{i}", "2.7.5.3")
                   for i in range(1, n + 1)])
    c.commit()
    return c  # giữ kết nối mở: dữ liệu còn nằm trong WAL như hệ cũ đang chạy


def test_sao_luu_lay_ca_du_lieu_trong_wal_va_xuat_danh_sach(tmp_path):
    src = tmp_path / "database.db"
    giu_mo = _db_cu(src, 7)
    r = sl.sao_luu(str(src), str(tmp_path / "daily"), dt.date(2026, 10, 2))
    giu_mo.close()
    assert r["so_may"] == 7 and pathlib.Path(r["ban_sao"]).name == "database_20261002.db"
    rows = pathlib.Path(r["danh_sach"]).read_text(encoding="utf-8-sig").splitlines()
    assert rows[0].startswith("hostname,mac,serial,room,ip,client_version") and len(rows) == 8
    assert "Phòng 301 - A6" in rows[1]
    assert not list((tmp_path / "daily").glob("*.tam"))


def test_sao_luu_giu_14_ban(tmp_path):
    src = tmp_path / "database.db"
    _db_cu(src).close()
    for d in range(1, 17):
        r = sl.sao_luu(str(src), str(tmp_path / "daily"), dt.date(2026, 9, d))
    assert len(list((tmp_path / "daily").glob("database_*.db"))) == 14
    assert len(list((tmp_path / "daily").glob("may_*.csv"))) == 14
    assert "database_20260901.db" in r["da_xoa"] or not (tmp_path / "daily" / "database_20260901.db").exists()


def test_sao_luu_khong_ghi_vao_nguon(tmp_path):
    src = tmp_path / "database.db"
    _db_cu(src).close()
    truoc = src.read_bytes()
    sl.sao_luu(str(src), str(tmp_path / "daily"), dt.date(2026, 10, 2))
    assert src.read_bytes() == truoc  # mở mode=ro: nguồn không đổi một byte


def test_sao_luu_loi_tra_ma_1(tmp_path):
    assert sl.main(["--nguon", str(tmp_path / "khong_co.db"), "--dich", str(tmp_path / "d")]) == 1


# ====================================================================== 0.7 cảnh báo online
def _may(n: int, online: bool = True, tat: float = 0, start: int = 1) -> list[dict]:
    return [{"hostname": f"A6-301-{i:02d}", "online": online, "tat_sach": tat, "nhan_lenh": online}
            for i in range(start, start + n)]


class _Tele:
    def __init__(self):
        self.tin: list[str] = []

    def __call__(self, text: str) -> None:
        self.tin.append(text)


def test_phan_tich_bo_qua_tat_co_chu_y_va_canary():
    now = 1_000_000.0
    prev = ["A6-301-01", "A6-301-02", "A6-301-03"]
    machines = [{"hostname": "a6-301-01", "online": False, "tat_sach": now - 60},   # tắt có chủ ý 1' trước
                {"hostname": "A6-301-02", "online": False, "tat_sach": 0},          # rớt thật
                {"hostname": "A6-301-03", "online": False, "tat_sach": 0}]          # canary đã sang Core
    on, rot = cb.phan_tich(prev, machines, {"A6-301-03"}, now)
    assert on == [] and rot == ["A6-301-02"]


@pytest.mark.parametrize("truoc,rot,bao", [(19, 19, False), (20, 4, False), (20, 5, True), (300, 29, False),
                                           (300, 30, True)])
def test_nguong_canh_bao(truoc, rot, bao):
    assert cb.can_bao(truoc, rot) is bao


def test_chay_bao_rot_hang_loat_mot_lan_moi_15_phut(tmp_path):
    t = _Tele()
    cb.chay(tmp_path, lambda: {"ok": True, "machines": _may(100)}, t, now=1000.0)
    assert not t.tin
    sau = _may(60) + _may(40, online=False, start=61)  # 40 máy rớt
    r = cb.chay(tmp_path, lambda: {"ok": True, "machines": sau}, t, now=1060.0)
    assert r["da_bao"] == ["rot"] and len(r["rot"]) == 40 and "40 máy rớt" in t.tin[0]
    # đợt rớt tiếp trong 15' không báo lại
    cb.chay(tmp_path, lambda: {"ok": True, "machines": _may(100)}, t, now=1120.0)
    cb.chay(tmp_path, lambda: {"ok": True, "machines": _may(50)}, t, now=1180.0)
    assert len(t.tin) == 1
    assert len((tmp_path / f"online_{dt.datetime.now():%Y%m%d}.csv").read_text().splitlines()) == 4


def test_chay_tan_hoc_tat_may_dang_hoang_khong_bao(tmp_path):
    t = _Tele()
    cb.chay(tmp_path, lambda: {"ok": True, "machines": _may(100)}, t, now=5000.0)
    tat = _may(100, online=False, tat=4990.0)
    cb.chay(tmp_path, lambda: {"ok": True, "machines": tat}, t, now=5060.0)
    assert not t.tin


def test_chay_mat_hub_bao_ngay_lan_2_va_bao_hoi(tmp_path):
    t = _Tele()

    def hong():
        raise ConnectionRefusedError("hub tắt")

    r1 = cb.chay(tmp_path, hong, t, now=100.0)
    assert r1["hub"].startswith("loi") and not t.tin  # 1 lần lỗi: chưa báo (tránh nhiễu khi hub vừa restart)
    cb.chay(tmp_path, hong, t, now=160.0)
    assert len(t.tin) == 1 and "KHÔNG gọi được hub" in t.tin[0]
    cb.chay(tmp_path, hong, t, now=220.0)
    assert len(t.tin) == 1  # trong 15' không báo lặp
    cb.chay(tmp_path, lambda: {"ok": True, "machines": _may(10)}, t, now=280.0)
    assert len(t.tin) == 2 and "đã trả lời lại" in t.tin[1]
    cb.chay(tmp_path, hong, t, now=340.0)
    cb.chay(tmp_path, lambda: {"ok": True, "machines": _may(10)}, t, now=400.0)
    assert len(t.tin) == 2  # lỗi 1 lần chưa từng báo → không báo "đã hồi"


def test_chay_sai_token_tinh_la_loi_hub(tmp_path):
    t = _Tele()
    for now in (10.0, 70.0):
        cb.chay(tmp_path, lambda: {"ok": False}, t, now=now)
    assert len(t.tin) == 1
