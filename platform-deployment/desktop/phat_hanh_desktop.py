"""Phát hành bản Desktop cho Tauri updater (Sổ tay 4.7) — đặt bộ cài đã ký vào kho tệp mà Core phục vụ ở `/desktop/`.

    uv run --project platform-core python platform-deployment/desktop/phat_hanh_desktop.py `
        --data-dir D:\\ITSupportPlatformData --base-url https://10.21.24.142:7443 --notes-file ghi_chu.txt

Ghi chú CÓ DẤU tiếng Việt: dùng `--notes-file` (tệp UTF-8). Tham số dòng lệnh đi qua launcher
`.venv\\Scripts\\python.exe` của uv (kể cả `uv run`) bị đổi chữ có dấu thành "?" — Python thật thì nhận đúng (đã thử
03/10/2026).

Trình tự (bài học phát hành agent hệ cũ — `version.txt` ghi CUỐI để máy khách không thấy bản mới khi bộ cài chưa sẵn):
1. Đọc phiên bản trong `tauri.conf.json`; lấy bộ cài NSIS + `.sig` do `pnpm tauri build` sinh ra.
2. Kiểm chữ ký: phải có, và (từ Tauri CLI 2.12) dòng "trusted comment" phải ghi ĐÚNG phiên bản — ứng dụng bật
   `requireSignedVersion` sẽ từ chối nếu lệch, kiểm ở đây để lỗi hiện lúc phát hành chứ không phải trên máy người dùng.
3. Chép bộ cài + chữ ký sang `<data-dir>/desktop/` (tên không dấu cách), mỗi tệp ghi tạm rồi đổi tên một lần.
4. Ghi `latest.json` SAU CÙNG. Giữ bản vừa phát hành + 2 bản số lớn nhất còn lại, xoá bản cũ hơn.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop-app"
GIU_LAI = 3


def doc_phien_ban(conf: Path) -> tuple[str, str]:
    c = json.loads(conf.read_text(encoding="utf-8"))
    return c["productName"], c["version"]


def tim_bo_cai(bundle: Path, product: str, version: str) -> tuple[Path, Path]:
    exe = bundle / f"{product}_{version}_x64-setup.exe"
    sig = exe.with_name(exe.name + ".sig")
    if not exe.is_file():
        raise SystemExit(f"Không thấy bộ cài {exe} — chạy `pnpm tauri build` (đặt khoá ký) trước")
    if not sig.is_file() or not sig.read_text(encoding="utf-8").strip():
        raise SystemExit(f"Thiếu chữ ký {sig} — build thiếu TAURI_SIGNING_PRIVATE_KEY?")
    return exe, sig


def kiem_chu_ky(sig_text: str, version: str) -> str:
    """Trả về dòng trusted comment; báo lỗi nếu chữ ký hỏng hoặc ghi phiên bản khác."""
    try:
        raw = base64.b64decode(sig_text.strip(), validate=True).decode("utf-8")
    except Exception as e:  # noqa: BLE001 — mọi lỗi giải mã đều là chữ ký hỏng
        raise SystemExit(f"Chữ ký không đọc được: {type(e).__name__}") from e
    tc = next((ln.split(":", 1)[1].strip() for ln in raw.splitlines() if ln.startswith("trusted comment:")), "")
    if not tc:
        raise SystemExit("Chữ ký thiếu dòng 'trusted comment'")
    m = re.search(r"version:(\S+)", tc)
    if m and m.group(1) != version:
        raise SystemExit(f"Chữ ký ghi phiên bản {m.group(1)} nhưng phát hành {version} — build lại")
    return tc


def _chep_nguyen_tu(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _ghi_nguyen_tu(dst: Path, text: str) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, dst)


def _phien_ban_so(name: str) -> tuple[int, ...]:
    m = re.search(r"_(\d+(?:\.\d+)*)_x64-setup\.exe$", name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def don_ban_cu(out: Path, hien_tai: str, giu: int = GIU_LAI) -> list[str]:
    """Giữ bản VỪA phát hành (kể cả khi là bản hạ cấp — latest.json đang trỏ tới nó) + các bản số lớn nhất còn lại."""
    khac = sorted((p for p in out.glob("*_x64-setup.exe") if p.name != hien_tai),
                  key=lambda p: _phien_ban_so(p.name), reverse=True)
    xoa = []
    for p in khac[giu - 1:]:
        for f in (p, p.with_name(p.name + ".sig")):
            if f.exists():
                f.unlink()
                xoa.append(f.name)
    return xoa


def phat_hanh(*, data_dir: Path, base_url: str, notes: str, conf: Path, bundle: Path,
              now: datetime | None = None) -> dict:
    product, version = doc_phien_ban(conf)
    exe, sig = tim_bo_cai(bundle, product, version)
    sig_text = sig.read_text(encoding="utf-8").strip()
    tc = kiem_chu_ky(sig_text, version)
    out = data_dir / "desktop"
    out.mkdir(parents=True, exist_ok=True)
    ten = f"{product.replace(' ', '-')}_{version}_x64-setup.exe"
    _chep_nguyen_tu(exe, out / ten)
    _chep_nguyen_tu(sig, out / (ten + ".sig"))
    latest = {
        "version": version,
        "notes": notes,
        "pub_date": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {"windows-x86_64": {"signature": sig_text, "url": f"{base_url.rstrip('/')}/desktop/{ten}"}},
    }
    _ghi_nguyen_tu(out / "latest.json", json.dumps(latest, ensure_ascii=False, indent=2) + "\n")  # SAU CÙNG
    return {"version": version, "file": ten, "size": (out / ten).stat().st_size, "trusted_comment": tc,
            "removed": don_ban_cu(out, ten)}


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        getattr(s, "reconfigure", lambda **_: None)(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Phát hành bản Desktop cho Tauri updater")
    ap.add_argument("--data-dir", required=True, type=Path, help="DATA_DIR của dịch vụ Core")
    ap.add_argument("--base-url", required=True, help="Địa chỉ Desktop dùng để tới Core, vd https://10.21.24.142:7443")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--notes", default="", help="Ghi chú phát hành KHÔNG dấu (hiện cho người dùng)")
    g.add_argument("--notes-file", type=Path, help="Tệp UTF-8 chứa ghi chú phát hành (dùng khi có dấu tiếng Việt)")
    ap.add_argument("--conf", type=Path, default=DESKTOP / "src-tauri" / "tauri.conf.json")
    ap.add_argument("--bundle", type=Path, default=DESKTOP / "src-tauri" / "target" / "release" / "bundle" / "nsis")
    a = ap.parse_args(argv)
    notes = a.notes_file.read_text(encoding="utf-8-sig").strip() if a.notes_file else a.notes
    if "?" in a.notes:
        print("CẢNH BÁO: ghi chú có dấu '?' — nếu là chữ có dấu bị mất thì chạy lại với --notes-file", file=sys.stderr)
    r = phat_hanh(data_dir=a.data_dir, base_url=a.base_url, notes=notes, conf=a.conf, bundle=a.bundle)
    print(f"PHÁT HÀNH OK: {r['version']} → {a.data_dir / 'desktop' / r['file']} ({r['size']:,} byte)")
    print(f"  chữ ký: {r['trusted_comment']}")
    if r["removed"]:
        print("  đã xoá bản cũ:", ", ".join(r["removed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
