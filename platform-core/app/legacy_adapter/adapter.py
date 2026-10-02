"""LegacyAdapter — ghép state RAM + cổng cập nhật + bộ ghi nền + gửi lệnh cho agent v2 (Sổ tay 3.3).

Gửi lệnh KHÔNG BAO GIỜ broadcast (luật A8): máy có socket → room `host_<HOST>` + theo dõi ACK (8 s × 3);
máy mất socket nhưng còn nhịp tim → hàng đợi HTTP `/check_command/<mac>`; máy tắt → kênh 'none' (báo lỗi).
Room phía Desktop luôn mang mã tổ chức: `t:<tenant_id>:{ps|pty|watch}:<mac12>`, `t:<tenant_id>:res:<token>`,
`t:<tenant_id>:devices` — để sau này nhiều tổ chức dùng chung một Core không nghe lẫn của nhau.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.config.settings import Settings
from app.legacy_adapter.identity import is_official_room, mac12, norm_host, norm_mac, room_from_hostname_raw
from app.legacy_adapter.state import LegacyState
from app.legacy_adapter.store import Store
from app.legacy_adapter.update_gate import SETTING_KEYS, UpdateGate
from app.legacy_adapter.writer import Writer, run_forever
from app.security.ipcheck import ip_allowed
from app.tenants.repo import SettingRepo

log = logging.getLogger("legacy")

# Lệnh tắt/khởi động lại máy (kể cả script tự soạn gọi shutdown.exe) — trừ `shutdown /a` (huỷ hẹn giờ). app.py 379.
_RE_LENH_TAT = re.compile(r"shutdown(?:\.exe)?\b(?![^\r\n]*[/-]a\b)[^\r\n]*[/-][sr]\b", re.I)
TENANT_RECHECK = 30.0


def co_y_tat_may(payload: dict) -> bool:
    """Lệnh này tắt/khởi động lại máy? → ghi mốc "tắt có chủ ý" NGAY lúc ra lệnh (hệ thi phân biệt với mất kết nối)."""
    try:
        if str(payload.get("command") or "").lower() in ("shutdown", "restart"):
            return True
        inner = payload.get("command_obj")
        obj: dict = inner if isinstance(inner, dict) else payload
        if str(obj.get("action") or "").lower() in ("shutdown", "restart"):
            return True
        return any(obj.get(k) and _RE_LENH_TAT.search(str(obj[k])) for k in ("script", "cmd", "command_line"))
    except Exception:
        return False


class LegacyAdapter:
    def __init__(self, db: Database, settings: Settings, socketio: Any):
        self.db = db
        self.s = settings
        self.sio = socketio
        self.state = LegacyState()
        self._tid: ObjectId | None = None
        self._tid_checked = -1e9
        self._gate: UpdateGate | None = None
        self._writer: Writer | None = None
        self.started = False
        self._last_report = self.state.clock()

    # ------------------------------------------------------------------ tổ chức + thư mục
    @property
    def tenant_id(self) -> ObjectId | None:
        """Tổ chức gắn với giao thức v2 (setting LEGACY_TENANT_CODE). Chưa có → thử lại sau 30 s."""
        if self._tid is None and self.state.clock() - self._tid_checked >= TENANT_RECHECK:
            self._tid_checked = self.state.clock()
            t = self.db.tenants.find_one({"code": self.s.LEGACY_TENANT_CODE, "status": "ACTIVE"}, {"_id": 1})
            self._tid = t["_id"] if t else None
            if self._tid is None:
                log.warning("Chưa có tổ chức %s đang hoạt động — agent v2 chỉ được trả lời tối thiểu",
                            self.s.LEGACY_TENANT_CODE)
        return self._tid

    @property
    def root(self) -> Path:
        return Path(self.s.DATA_DIR) / self.s.LEGACY_TENANT_CODE

    def store(self) -> Store | None:
        tid = self.tenant_id
        return Store(self.db, tid, self.root) if tid else None

    @property
    def gate(self) -> UpdateGate:
        if self._gate is None:
            self._gate = UpdateGate(self.root / "updates", self.update_settings)
        return self._gate

    def update_settings(self) -> dict:
        tid = self.tenant_id
        if not tid:
            return {}
        rows = SettingRepo(self.db, tid).find({"key": {"$in": list(SETTING_KEYS)}}, {"key": 1, "value": 1})
        return {r["key"]: r.get("value") for r in rows}

    def ip_ok(self, ip: str) -> bool:
        return ip_allowed(ip, list(self.s.LEGACY_ALLOWED_CIDRS))

    # ------------------------------------------------------------------ room phía Desktop
    def room_dev(self, kind: str, mac: str) -> str:
        return f"t:{self.tenant_id}:{kind}:{mac12(mac)}"

    def room_res(self, token: str) -> str:
        return f"t:{self.tenant_id}:res:{token}"

    def room_devices(self) -> str:
        return f"t:{self.tenant_id}:devices"

    # ------------------------------------------------------------------ 2 route nóng (gọi từ fastpath.py)
    def handle_update(self, data: dict, ip: str) -> dict:
        """POST /update — A1: luôn 200 (lớp gọi tự bọc lỗi); A3: mất socket → reconnect_socket, xét TRƯỚC mọi nhánh."""
        if not self.ip_ok(ip):
            return {"status": "success"}  # sai dải IP: không nhận dữ liệu nhưng KHÔNG làm agent đi săn server
        host = self.state.ingest(data, ip)
        if not host:
            return {"status": "error"}  # 200: thiếu hostname (hub cũ trả 400 — luật A1 cấm)
        if not self.state.has_socket(host):
            return {"status": "success", "action": "reconnect_socket"}
        return {"status": "success"}  # KHÔNG BAO GIỜ 426/kill_and_update (A2)

    def handle_check_command(self, mac: str) -> dict:
        """GET /check_command/<mac> — hàng đợi lệnh HTTP (FIFO, lệnh quá 5' bị bỏ)."""
        cmd = self.state.pop_command(mac)
        if isinstance(cmd, str):
            if cmd in ("shutdown", "restart"):
                self.state.mark_offline(self.state.host_for_mac(mac), "lenh_tat")
            return {"command": cmd}
        if isinstance(cmd, dict):
            return {"command_obj": cmd}
        return {"command": None}

    # ------------------------------------------------------------------ gửi lệnh (A8)
    def dispatch(self, host: str, mac: str, payload: dict, *, command_id: str | None = None) -> dict:
        st = self.state
        host = norm_host(host) or st.host_for_mac(mac)
        known = st.hosts.get(host)
        mac = norm_mac(mac) or (known.mac if known else "")
        cid = command_id or uuid.uuid4().hex
        msg = {**payload, "command_id": cid, "mac": mac, "hostname": host}
        if host and co_y_tat_may(msg):
            st.tat_sach[host] = st.clock()
        ch = st.channel(host) if host else "none"
        if ch == "socket":
            st.track(cid, host, mac, msg)
            self.sio.emit("execute_command", msg, to=f"host_{host}")
            st.counters["cmd_socket"] += 1
        elif ch == "http" and mac:
            if isinstance(payload.get("command"), str):
                item: Any = payload["command"]
            else:
                item = {**(payload.get("command_obj") or {}), "command_id": cid}
            st.enqueue(mac, item)
            st.counters["cmd_http"] += 1
        else:
            ch = "none"
        return {"command_id": cid, "channel": ch, "hostname": host}

    def retry_tick(self) -> None:
        resend, failed = self.state.due_retries()
        for cid, info in resend:
            self.sio.emit("execute_command", info["payload"], to=f"host_{info['host']}")
            log.info("ACK-RETRY lệnh %s -> %s (lần %d)", cid[:8], info["host"], info["tries"])
        for cid, info in failed:
            log.warning("ACK-FAIL lệnh %s -> %s sau %d lần", cid[:8], info["host"], info["tries"])

    def send_to_host(self, event: str, data: dict, host: str) -> bool:
        """Gửi 1 sự kiện tới ĐÚNG máy (room host_<HOST>). Máy chưa có socket → False, không broadcast."""
        host = norm_host(host)
        if not host or not self.state.has_socket(host):
            return False
        self.sio.emit(event, data, to=f"host_{host}")
        return True

    def send_ps_input(self, mac: str, data: str) -> bool:
        """Phím gõ cho phiên PowerShell — hub cũ broadcast mọi agent; Core tra MAC → máy rồi gửi trúng đích."""
        host = self.state.host_for_mac(mac)
        return self.send_to_host("server_ps_input", {"mac": norm_mac(mac), "data": data}, host)

    def send_fs_request(self, host: str, data: dict, reply_sid: str) -> bool:
        return self.send_to_host("fs_request", {**data, "hostname": norm_host(host), "reply_sid": reply_sid}, host)

    def send_vnc_thumb_req(self, host: str, reply_sid: str, hd: bool = False) -> bool:
        return self.send_to_host("vnc_thumb_req", {"hostname": norm_host(host), "reply_sid": reply_sid,
                                                   "hd": bool(hd)}, host)

    def emit(self, event: str, data: Any, room: str) -> None:
        self.sio.emit(event, data, to=room)

    # ------------------------------------------------------------------ vòng nền
    def writer(self) -> Writer | None:
        tid = self.tenant_id
        if tid is None:
            return None
        if self._writer is None:
            self._writer = Writer(self.db, tid, self.state)
        return self._writer

    def writer_tick(self) -> int:
        """Một nhịp ghi nền; trả số máy đã ghi xuống `computers` (0 khi chưa có tổ chức)."""
        w = self.writer()
        if w is None:
            self.state.sweep()
            return 0
        n = w.tick()
        self._emit_devices(w)
        self._report()
        return n

    def _emit_devices(self, w: Writer) -> None:
        changed, self.state.ui_changed = self.state.ui_changed, set()
        if not changed:
            return
        devs = []
        for host in changed:
            h = self.state.hosts.get(host)
            if h is None:
                continue
            d = {"hostname": h.hostname or host, "room_name": w.room_of(host, h.hostname), "is_online": h.online}
            if h.online:
                d.update({k: h.hb.get(k) for k in ("cpu_usage", "ram_usage", "disk_usage", "client_version")})
            devs.append(d)
        total = sum(1 for x in self.state.online_hosts() if is_official_room(w.room_of(x)))
        self.emit("legacy_devices", {"devices": devs, "total_online": total}, self.room_devices())

    def _report(self) -> None:
        now = self.state.clock()
        if now - self._last_report < 60:
            return
        self._last_report = now
        c = self.state.counters
        log.info("SYNC %d nhịp tim/60s · %d poll · online %d · socket %d · lệnh socket %d / http %d · ACK gửi lại %d "
                 "/ bỏ cuộc %d · hàng đợi http %d MAC", c["hb"], c["poll"], len(self.state.online_hosts()),
                 len(self.state.registered), c["cmd_socket"], c["cmd_http"], c["ack_retry"], c["ack_fail"],
                 len(self.state.queue))
        for k in c:
            c[k] = 0

    def start(self) -> None:
        """Chạy 2 vòng nền (gọi trong app.server.main; test gọi tick trực tiếp)."""
        if self.started:
            return
        self.started = True
        self.sio.start_background_task(run_forever, self.writer_tick, self.sio.sleep, 2.0, "ghi computers")
        self.sio.start_background_task(run_forever, self.retry_tick, self.sio.sleep, 2.0, "gửi lại lệnh")
        log.info("Bộ tương thích agent v2 chạy cho tổ chức %s (dữ liệu %s)", self.s.LEGACY_TENANT_CODE, self.root)

    # ------------------------------------------------------------------ tiện ích cho API/hệ thi
    def room_of(self, host: str) -> str:
        """Phòng hiệu lực của máy (ưu tiên chuyển phòng tay khi bộ ghi đã nạp)."""
        host = norm_host(host)
        h = self.state.hosts.get(host)
        name = (h.hostname if h else "") or host
        return self._writer.room_of(host, name) if self._writer else room_from_hostname_raw(name)

    def snapshot(self) -> list[dict]:
        now = self.state.clock()
        out = []
        for h in self.state.hosts.values():
            if not self.state.is_online(h.host):
                continue
            out.append({"hostname": h.hostname or h.host, "mac": h.mac, "ip": h.hb.get("ip") or h.seen_ip,
                        "room_name": self.room_of(h.host),
                        "channel": self.state.channel(h.host), "last_seen_s": round(now - h.last_seen, 1),
                        "client_version": h.hb.get("client_version")})
        return sorted(out, key=lambda d: d["hostname"])

    def tat_sach_since(self, host: str) -> datetime | None:
        ts = self.state.tat_sach.get(norm_host(host))
        return datetime.fromtimestamp(ts, UTC) if ts else None
