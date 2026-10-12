"""Kho bản phát hành agent v2 (Sổ tay 8.4) — người vận hành chạy trên máy chủ.

    uv run python -m app.legacy_adapter.release_cli nhap [--tu D:\\NetworkInventory\\updates]
    uv run python -m app.legacy_adapter.release_cli ds
    uv run python -m app.legacy_adapter.release_cli phat-hanh <bản>

nhap       Chép Client_Management.exe + manifest.json (+ version.txt) từ một thư mục phát hành (mặc định thư mục updates
           của hệ cũ — CHỈ ĐỌC) vào kho của Core, sau khi kiểm SHA-256 + size khớp manifest. KHÔNG phát hành.
ds         Liệt kê các bản trong kho (* = đang phát).
phat-hanh  Đưa một bản trong kho thành bản đang phát (giống nút trên Desktop). Không tự đẩy xuống máy nào — cổng chia
           đợt mặc định tắt; máy chỉ lên bản mới khi bấm cập nhật máy chọn / bật All Update.
Kho: <DATA_DIR>/<LEGACY_TENANT_CODE>/updates/releases/<bản>/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.settings import get_settings
from app.legacy_adapter.releases import LoiBanPhatHanh, Releases
from app.utils.console import utf8_stdio

CU = Path(r"D:\NetworkInventory\updates")


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="release_cli")
    sub = ap.add_subparsers(dest="lenh", required=True)
    p = sub.add_parser("nhap")
    p.add_argument("--tu", default=str(CU))
    sub.add_parser("ds")
    p = sub.add_parser("phat-hanh")
    p.add_argument("ban")
    a = ap.parse_args(argv)
    s = get_settings()
    rel = Releases(Path(s.DATA_DIR) / s.LEGACY_TENANT_CODE / "updates")
    try:
        if a.lenh == "nhap":
            r = rel.import_dir(Path(a.tu))
            print(f"Đã nhập bản {r['version']} ({r['size']:,} byte, sha256 {r['sha256'][:12]}…) vào {rel.root}")
        elif a.lenh == "ds":
            for r in rel.list():
                mark = "*" if r["active"] else " "
                tt = "OK" if r["valid"] else "HỎNG: " + r["problem"]
                print(f" {mark} {r['version']:<12} {r['size']:>12,} byte  {tt}")
            if not rel.list():
                print("(kho trống)")
        else:
            r = rel.activate(a.ban)
            print(f"Bản đang phát: {r['version']} — chưa máy nào tự cập nhật cho tới khi bấm trên Desktop.")
    except LoiBanPhatHanh as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
