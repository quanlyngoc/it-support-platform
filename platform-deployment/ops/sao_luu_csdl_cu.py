"""Sổ tay bước 0.6 — sao lưu CSDL hệ cũ (D:\\NetworkInventory\\database.db) hằng ngày. CHỈ ĐỌC hệ cũ.

- Mở nguồn ở chế độ CHỈ ĐỌC (`mode=ro`) và chép bằng API backup của SQLite: CSDL hệ cũ chạy WAL, tệp -wal có lúc
  LỚN HƠN tệp chính (đo 02/10/2026: 36 MB vs 30 MB) → chép tệp thô sẽ MẤT dữ liệu chưa checkpoint. Chép một lượt
  (pages=-1, ≈ 0,3 s với 30 MB); WAL nên người đọc không chặn hub đang ghi.
- Kiểm `pragma integrity_check` + đếm máy trên BẢN SAO. Giữ GIU_LAI bản gần nhất.
- Kèm ảnh chụp danh sách máy ra CSV (bài học 10.21: dò máy mất phải đối chiếu với ảnh chụp danh sách).

    python sao_luu_csdl_cu.py [--nguon D:\\NetworkInventory\\database.db] [--dich D:\\Backup\\daily]
Thoát 0 = đạt; khác 0 = lỗi (Task Scheduler ghi Last Run Result ≠ 0x0).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import sqlite3
import sys

GIU_LAI = 14
NGUON = r"D:\NetworkInventory\database.db"
DICH = r"D:\Backup\daily"
_COT_MAY = ("hostname", "mac", "serial", "room", "room_override", "ip", "client_version", "model", "last_update")


def sao_luu(nguon: str, dich: str, hom_nay: dt.date | None = None, giu: int = GIU_LAI) -> dict:
    ngay = (hom_nay or dt.date.today()).strftime("%Y%m%d")
    out = pathlib.Path(dich)
    out.mkdir(parents=True, exist_ok=True)
    db_dich = out / f"database_{ngay}.db"
    tam = db_dich.with_suffix(".db.tam")
    tam.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{pathlib.Path(nguon).as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        dst = sqlite3.connect(tam)
        try:
            src.backup(dst)  # một lượt — từng khối nhỏ sẽ bị khởi động lại liên tục vì hub ghi mỗi giây
        finally:
            dst.close()
    finally:
        src.close()

    chk = sqlite3.connect(tam)
    try:
        ok = chk.execute("pragma integrity_check").fetchone()[0]
        so_may = chk.execute("select count(*) from computers").fetchone()[0]
        cols = {r[1] for r in chk.execute("pragma table_info(computers)")}
        lay = [c for c in _COT_MAY if c in cols]
        rows = chk.execute(f"select {', '.join(lay)} from computers order by hostname").fetchall()
    finally:
        chk.close()
    if ok != "ok":
        raise RuntimeError(f"Bản sao hỏng: integrity_check = {ok}")
    tam.replace(db_dich)  # chỉ đổi tên khi bản sao đã kiểm đạt → không bao giờ để lại bản dở dang trông như bản tốt

    csv_dich = out / f"may_{ngay}.csv"
    with csv_dich.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel mở đúng tiếng Việt
        w = csv.writer(f)
        w.writerow(lay)
        w.writerows(rows)

    xoa = []
    for mau in ("database_*.db", "may_*.csv"):
        cu = sorted(out.glob(mau))
        for p in cu[:-giu] if giu > 0 else []:
            p.unlink()
            xoa.append(p.name)
    return {"ban_sao": str(db_dich), "danh_sach": str(csv_dich), "so_may": so_may,
            "dung_luong_mb": round(db_dich.stat().st_size / 1048576, 1), "da_xoa": xoa}


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        getattr(s, "reconfigure", lambda **_: None)(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--nguon", default=NGUON)
    ap.add_argument("--dich", default=DICH)
    a = ap.parse_args(argv)
    try:
        r = sao_luu(a.nguon, a.dich)
        dong = (f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} OK {r['ban_sao']} ({r['dung_luong_mb']} MB, {r['so_may']} may)"
                + (f" · da xoa {len(r['da_xoa'])} ban cu" if r["da_xoa"] else ""))
        ma = 0
    except Exception as e:  # mọi lỗi → mã thoát 1 để Task Scheduler báo (Last Run Result ≠ 0x0)
        dong = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} LOI sao luu: {type(e).__name__}: {e}"
        ma = 1
    print(dong, file=sys.stderr if ma else sys.stdout)
    _ghi_nhat_ky(pathlib.Path(a.dich) / "sao_luu.log", dong)  # Task Scheduler không giữ stdout
    return ma


def _ghi_nhat_ky(p: pathlib.Path, dong: str) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(dong + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
