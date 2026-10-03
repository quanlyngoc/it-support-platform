"""Lệnh quản trị sơ đồ phòng (Sổ tay 5.3).

    uv run python -m app.rooms.maps_cli nhap-cu --tenant PHENIKAA [--dir <kho cũ>] [--ghi-de] [--thu]
    uv run python -m app.rooms.maps_cli xuat --tenant PHENIKAA [--dir <thư mục xuất>]

nhap-cu  Đọc tệp sơ đồ của hệ cũ (CHỈ ĐỌC; mặc định LEGACY_MAPS_DIR) → `rooms.map`. Phòng đã có sơ đồ trong Core thì
         bỏ qua, trừ khi `--ghi-de`. `--thu` chỉ in kết quả, không ghi gì.
xuat     Ghi lại MỌI sơ đồ của Core ra tệp định dạng cũ (mặc định MAPS_EXPORT_DIR hoặc <DATA_DIR>/<MÃ>/Maps) — dùng khi
         đổi thư mục xuất cho hệ thi, hoặc khi lần lưu trước báo xuất lỗi.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config.settings import get_settings
from app.db.client import get_db
from app.rooms import maps
from app.rooms.map_routes import export_dir
from app.rooms.service import ensure_room
from app.tenants import service as tsvc
from app.tenants.repo import repo_for
from app.utils.console import utf8_stdio


def nhap_cu(db, tenant: dict, src: Path, ghi_de: bool, thu: bool) -> int:
    rooms = repo_for(db, tenant["_id"], "rooms")
    n = 0
    for fp in sorted(src.glob("*.json")):
        name = fp.stem.replace("_", " ")
        try:
            m = maps.from_legacy(json.loads(fp.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"  BỎ QUA {fp.name}: {type(e).__name__}: {e}")
            continue
        doc = rooms.find_one({"name": name}, {"map": 1})
        if doc is not None and doc.get("map") and not ghi_de:
            print(f"  giữ nguyên {name} (Core đã có sơ đồ)")
            continue
        pcs = sum(1 for it in m.items if it.kind == "pc")
        print(f"  {'(thử) ' if thu else ''}{name}: {pcs} máy, {len(m.items)} phần tử")
        if not thu:
            rid = ensure_room(db, tenant["_id"], name)
            rooms.update_by_id(rid, {"$set": {"map": m.model_dump(), "map_updated_at": datetime.now(UTC),
                                              "map_updated_by": "nhap-cu"}})
        n += 1
    return n


def xuat(db, tenant: dict, out: Path) -> int:
    n = 0
    for r in repo_for(db, tenant["_id"], "rooms").find({"map": {"$ne": None, "$exists": True}}, {"name": 1, "map": 1}):
        fp = maps.export_file(out, r["name"], maps.MapModel.model_validate(r["map"]))
        print(f"  {fp}")
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="app.rooms.maps_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("nhap-cu", help="Nhập sơ đồ từ kho tệp của hệ cũ (chỉ đọc)")
    a.add_argument("--tenant", required=True)
    a.add_argument("--dir", default="")
    a.add_argument("--ghi-de", action="store_true")
    a.add_argument("--thu", action="store_true")
    b = sub.add_parser("xuat", help="Xuất mọi sơ đồ ra tệp định dạng cũ cho hệ thi")
    b.add_argument("--tenant", required=True)
    b.add_argument("--dir", default="")
    args = ap.parse_args(argv)
    s = get_settings()
    db = get_db()
    t = tsvc.get_tenant_by_code(db, args.tenant)
    if not t:
        print(f"Không có tổ chức {args.tenant}", file=sys.stderr)
        return 1
    if args.cmd == "nhap-cu":
        src = Path(args.dir or s.LEGACY_MAPS_DIR)
        if not src.is_dir():
            print(f"Không thấy thư mục sơ đồ cũ: {src}", file=sys.stderr)
            return 1
        print(f"Nhập sơ đồ cũ từ {src} (chỉ đọc) → tổ chức {t['code']}")
        print(f"Xong: {nhap_cu(db, t, src, args.ghi_de, args.thu)} phòng")
    else:
        out = Path(args.dir) if args.dir else export_dir(s, t["code"])
        print(f"Xuất sơ đồ định dạng cũ → {out}")
        print(f"Xong: {xuat(db, t, out)} phòng")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
