"""Cổng cập nhật agent v2 (luật A4/A5, Sổ tay 3.4).

- `/check_update` mặc định trả "không có bản mới" `{"version":"0.0.0.0","hash":"","size":0}` — luôn 200 + khoá `version`
  (agent dùng chính endpoint này nhận diện "đúng server của ta" khi săn server).
- Chỉ mời cập nhật khi: bộ cài tồn tại và KHỚP manifest.json (SHA-256 + size) VÀ máy lọt một cổng chia đợt.
- Cổng chia đợt đọc từ `settings` của tổ chức (mặc định TẤT CẢ TẮT):
    update.all (bool) · update.hosts [tên máy] · update.rollout_rooms ["405", …] · update.rollout_percent (0-100)
- Thư mục bộ cài: <DATA_DIR>/<MÃ TỔ CHỨC>/updates/{Client_Management.exe, manifest.json, version.txt}.
"""
from __future__ import annotations

import hashlib
import json
import time
import zlib
from collections.abc import Callable
from pathlib import Path

from app.legacy_adapter.identity import norm_host, room_number

CLOSED = {"version": "0.0.0.0", "hash": "", "size": 0}
INSTALLER = "Client_Management.exe"  # tên BỘ CÀI (Inno Setup) — khác Client_Manager.exe là agent (bài học 10.19)
SETTING_KEYS = ("update.all", "update.hosts", "update.rollout_rooms", "update.rollout_percent")
DL_MAX = 60     # tối đa 60 lượt tải bắt đầu trong DL_HOLD giây (app.py 2177)
DL_HOLD = 45.0


class UpdateGate:
    MANIFEST_TTL = 15.0
    POLICY_TTL = 30.0

    def __init__(self, updates_dir: Path, load_settings: Callable[[], dict],
                 clock: Callable[[], float] = time.monotonic):
        self.dir = updates_dir
        self._load_settings = load_settings
        self.clock = clock
        self._manifest: tuple[float, dict | None] = (-1e9, None)
        self._policy: tuple[float, dict] = (-1e9, {})
        self._hash_cache: tuple[tuple[int, int], str] | None = None

    @property
    def installer(self) -> Path:
        return self.dir / INSTALLER

    # ------------------------------------------------------------------ bộ cài + manifest
    def _sha256(self, p: Path) -> str:
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size)
        if self._hash_cache and self._hash_cache[0] == key:
            return self._hash_cache[1]
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        self._hash_cache = (key, h.hexdigest())
        return self._hash_cache[1]

    def _read_manifest(self) -> dict | None:
        try:
            m = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8-sig"))
            sha = str(m.get("sha256") or "").strip().lower()
            size = int(m.get("size") or 0)
            vf = self.dir / "version.txt"
            version = (vf.read_text(encoding="utf-8-sig").strip() if vf.exists() else "") or str(m.get("version") or "")
            exe = self.installer
            if len(sha) != 64 or size <= 0 or not version or not exe.is_file():
                return None
            if exe.stat().st_size != size or self._sha256(exe) != sha:
                return None  # bộ cài lệch manifest (build dừng giữa chừng — bài học 10.19) → KHÔNG mời cập nhật
            return {"version": version, "hash": sha, "size": size}
        except (OSError, ValueError, TypeError):
            return None

    def manifest(self) -> dict | None:
        ts, val = self._manifest
        if self.clock() - ts < self.MANIFEST_TTL:
            return val
        val = self._read_manifest()
        self._manifest = (self.clock(), val)
        return val

    # ------------------------------------------------------------------ cổng chia đợt
    def policy(self) -> dict:
        ts, val = self._policy
        if self.clock() - ts < self.POLICY_TTL:
            return val
        try:
            raw = self._load_settings() or {}
        except Exception:
            raw = {}  # không đọc được cấu hình → coi như TẮT (an toàn: không cập nhật)
        try:
            pct = max(0, min(100, int(raw.get("update.rollout_percent") or 0)))
        except (TypeError, ValueError):
            pct = 0
        val = {"all": bool(raw.get("update.all")),
               "hosts": {norm_host(h) for h in (raw.get("update.hosts") or []) if norm_host(h)},
               "rooms": {room_number(r) for r in (raw.get("update.rollout_rooms") or []) if room_number(r)},
               "percent": pct}
        self._policy = (self.clock(), val)
        return val

    def invalidate(self) -> None:
        self._manifest = (-1e9, None)
        self._policy = (-1e9, {})

    def decide(self, ip: str, host: str = "", room: str = "") -> dict:
        m = self.manifest()
        if not m:
            return dict(CLOSED)
        p = self.policy()
        if p.get("all") or (host and host in p.get("hosts", ())):
            return dict(m)
        if room and room_number(room) in p.get("rooms", ()):
            return dict(m)
        pct = p.get("percent", 0)
        if pct and ip and zlib.crc32(ip.encode()) % 100 < pct:
            return dict(m)
        return dict(CLOSED)
