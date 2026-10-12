"""Kho bản phát hành agent v2 (Sổ tay 8.4) — giữ NHIỀU bản để "Cài lại bản cũ" cho máy chọn.

    <DATA_DIR>/<MÃ TỔ CHỨC>/updates/                  ← bản ĐANG PHÁT (UpdateGate đọc; /download_setup phục vụ)
        Client_Management.exe · manifest.json · version.txt
    <DATA_DIR>/<MÃ TỔ CHỨC>/updates/releases/<bản>/   ← kho các bản (Client_Management.exe + manifest.json)

- `import_dir`: chép bộ cài từ một thư mục phát hành (vd. D:\\NetworkInventory\\updates — CHỈ ĐỌC) vào kho, sau khi KIỂM
  SHA-256 + size khớp manifest (bộ cài lệch manifest = build dừng giữa chừng, bài học 10.19 → từ chối).
- `activate`: đưa một bản trong kho thành bản đang phát, đúng thứ tự của `publish_release.ps1` hệ cũ: bộ cài (.part →
  os.replace) → manifest.json → version.txt CUỐI CÙNG. Việc đổi bản đang phát KHÔNG tự đẩy gì xuống máy: cổng chia đợt
  mặc định tắt hết (A4); máy chỉ lên bản mới khi người vận hành bấm cập nhật máy chọn / bật All Update.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.legacy_adapter.update_gate import INSTALLER

_VER = re.compile(r"^\d+(\.\d+){1,3}$")


class LoiBanPhatHanh(ValueError):
    pass


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def version_key(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except ValueError:
        return (0,)


def _read(dirp: Path, *, version_file: bool) -> dict:
    """Đọc + KIỂM một thư mục phát hành. Trả {version, sha256, size}; lỗi → LoiBanPhatHanh (nói rõ lý do)."""
    exe, mf = dirp / INSTALLER, dirp / "manifest.json"
    if not exe.is_file():
        raise LoiBanPhatHanh(f"Không có {INSTALLER} trong {dirp}")
    if not mf.is_file():
        raise LoiBanPhatHanh(f"Không có manifest.json trong {dirp} — bản build chưa phát hành xong (bài học 10.19)")
    try:
        m = json.loads(mf.read_text(encoding="utf-8-sig"))
    except ValueError:
        raise LoiBanPhatHanh("manifest.json hỏng") from None
    sha, size = str(m.get("sha256") or "").strip().lower(), int(m.get("size") or 0)
    ver = str(m.get("version") or "").strip()
    vf = dirp / "version.txt"
    if version_file and vf.is_file():
        ver = vf.read_text(encoding="utf-8-sig").strip() or ver
    if not _VER.match(ver):
        raise LoiBanPhatHanh(f"Không xác định được phiên bản (manifest/version.txt): {ver!r}")
    if len(sha) != 64 or size <= 0:
        raise LoiBanPhatHanh("manifest.json thiếu sha256 / size")
    if exe.stat().st_size != size or _sha256(exe) != sha:
        raise LoiBanPhatHanh(f"{INSTALLER} KHÔNG khớp manifest (sha256/size) — không dùng bộ cài này")
    return {"version": ver, "sha256": sha, "size": size}


class Releases:
    def __init__(self, updates_dir: Path):
        self.updates = updates_dir
        self.root = updates_dir / "releases"

    def dir_of(self, version: str) -> Path:
        if not _VER.match(version or ""):
            raise LoiBanPhatHanh("Phiên bản không hợp lệ")
        return self.root / version

    def get(self, version: str) -> dict | None:
        """Bản trong kho còn nguyên vẹn (khớp manifest) → {version, sha256, size, path}; không → None."""
        try:
            d = self.dir_of(version)
            info = _read(d, version_file=False)
        except LoiBanPhatHanh:
            return None
        return {**info, "path": d / INSTALLER} if info["version"] == version else None

    def current(self) -> dict | None:
        try:
            return _read(self.updates, version_file=True)
        except LoiBanPhatHanh:
            return None

    def list(self) -> list[dict]:
        cur = self.current()
        out = []
        if self.root.is_dir():
            for d in self.root.iterdir():
                if not d.is_dir() or not _VER.match(d.name):
                    continue
                try:
                    info, ok, why = _read(d, version_file=False), True, ""
                except LoiBanPhatHanh as e:
                    info, ok, why = {"version": d.name, "sha256": "", "size": 0}, False, str(e)
                st = (d / INSTALLER).stat().st_mtime if (d / INSTALLER).exists() else 0
                active = bool(cur and cur["sha256"] == info["sha256"])
                out.append({**info, "valid": ok, "problem": why, "active": active,
                            "added_at": datetime.fromtimestamp(st, UTC).isoformat() if st else None})
        out.sort(key=lambda r: version_key(r["version"]), reverse=True)
        return out

    def _copy(self, src: Path, dst: Path) -> None:
        tmp = dst.with_name(dst.name + ".part")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)

    def import_dir(self, src: Path) -> dict:
        """Chép bản phát hành (bộ cài + manifest) từ `src` vào kho. Chỉ ĐỌC `src`."""
        info = _read(src, version_file=True)
        d = self.dir_of(info["version"])
        d.mkdir(parents=True, exist_ok=True)
        self._copy(src / INSTALLER, d / INSTALLER)
        (d / "manifest.json").write_text(json.dumps(
            {"version": info["version"], "sha256": info["sha256"], "size": info["size"]}), encoding="utf-8")
        got = _read(d, version_file=False)  # kiểm lại bản trong kho (chép hỏng = lỗi ngay, không để dành)
        return got

    def activate(self, version: str) -> dict:
        rel = self.get(version)
        if rel is None:
            raise LoiBanPhatHanh(f"Không có bản {version} nguyên vẹn trong kho")
        self.updates.mkdir(parents=True, exist_ok=True)
        # thứ tự của publish_release.ps1: bộ cài → manifest → version.txt CUỐI (đọc dở giữa chừng: manifest lệch bộ cài
        # thì UpdateGate trả "không có bản mới" — không bao giờ mời tải bộ cài hỏng)
        self._copy(rel["path"], self.updates / INSTALLER)
        mf = self.updates / "manifest.json.part"
        mf.write_text(json.dumps({"version": version, "sha256": rel["sha256"], "size": rel["size"]}), encoding="utf-8")
        os.replace(mf, self.updates / "manifest.json")
        vf = self.updates / "version.txt.part"
        vf.write_text(version, encoding="utf-8")
        os.replace(vf, self.updates / "version.txt")
        cur = self.current()
        if not cur or cur["version"] != version:
            raise LoiBanPhatHanh("Phát hành không thành công — kiểm thư mục updates")
        return cur
