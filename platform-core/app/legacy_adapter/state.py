"""Trạng thái RAM của bộ tương thích agent v2 — MỘT tiến trình Core duy nhất phục vụ agent (HOP_DONG mục B).

Đường nóng (≈ 440 nhịp tim/s + ≈ 400 poll lệnh/s) chỉ đụng dict trong RAM, KHÔNG chạm CSDL; bộ ghi nền
(writer.py) mới đưa xuống MongoDB. Lớp này không biết Flask/Socket.IO để test được thuần.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.legacy_adapter.identity import norm_host, norm_mac

# Trường nhịp tim được giữ (client.py 4133-4144); trường lạ bị bỏ để không phình RAM/CSDL
HB_FIELDS = ("hostname", "ip", "mac", "cpu", "ram", "mainboard", "disk", "model", "serial", "network", "cpu_usage",
             "ram_usage", "disk_usage", "cpu_temp", "cpu_fan", "cmos_battery", "client_version")
OFFLINE_AFTER = 35.0   # giây không nhịp tim → offline (giống watchdog hub cũ)
QUEUE_TTL = 300.0      # lệnh xếp hàng HTTP quá 5' thì bỏ: máy bật lại sau vài giờ không được chạy "shutdown" cũ
QUEUE_MAX = 50         # mỗi MAC tối đa 50 lệnh chờ (WoL cả phòng qua 1 máy relay)
ACK_TIMEOUT = 8.0      # app.py 370
ACK_MAX_TRIES = 3      # app.py 371
MAX_HOSTS = 20000      # chặn phình RAM khi bị gửi tên máy rác (giao thức v2 không xác thực)
_MAX_STR = 1000


@dataclass
class Host:
    host: str                       # khoá: tên máy VIẾT HOA
    hostname: str = ""              # như agent gửi
    mac: str = ""                   # aa:bb:cc:dd:ee:ff
    seen_ip: str = ""               # IP nhìn từ Core (qua Caddy) — dùng cho cổng cập nhật
    hb: dict = field(default_factory=dict)
    last_seen: float = 0.0
    online: bool = False
    state_dirty: bool = False       # vừa đổi online/offline → bộ ghi ghi ngay ở nhịp kế
    written_at: float = 0.0         # lần ghi `computers` gần nhất (đồng hồ của state)
    offline_reason: str = ""


def _clean(v: Any) -> Any:
    if isinstance(v, str):
        return v[:_MAX_STR]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return str(v)[:_MAX_STR]


class LegacyState:
    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.hosts: dict[str, Host] = {}
        self.mac_host: dict[str, str] = {}          # aa:bb:.. → HOST
        self.ip_host: dict[str, str] = {}           # IP nhìn từ Core → HOST
        self.registered: dict[str, str] = {}        # HOST → sid socket đang giữ kênh lệnh
        self.sid_hosts: dict[str, set[str]] = {}    # sid → {HOST}
        self.queue: dict[str, deque] = {}           # mac → deque[(ts, lệnh)]
        self.pending: dict[str, dict] = {}          # command_id → {host, mac, payload, ts, tries}
        self.ack_failed: dict[str, dict] = {}       # command_id → {host, tries, reason, ts} (tối đa 2000)
        self.tat_sach: dict[str, float] = {}        # HOST → lúc máy báo "tắt có chủ ý" (hệ thi đọc)
        self.dl_slots: list[float] = []
        self.ui_changed: set[str] = set()           # máy đổi trạng thái/số liệu chờ phát realtime
        self.counters = {"hb": 0, "poll": 0, "cmd_http": 0, "cmd_socket": 0, "ack_retry": 0, "ack_fail": 0}

    # ------------------------------------------------------------------ nhịp tim
    def ingest(self, data: dict, seen_ip: str = "") -> str | None:
        """Ghi nhận 1 nhịp tim. Trả HOST, hoặc None nếu thiếu hostname. Không bao giờ ném lỗi vì dữ liệu lạ."""
        host = norm_host(data.get("hostname"))
        if not host:
            return None
        now = self.clock()
        h = self.hosts.get(host)
        if h is None:
            if len(self.hosts) >= MAX_HOSTS:
                return host  # quá trần: vẫn trả lời agent bình thường, chỉ không theo dõi thêm
            h = self.hosts[host] = Host(host=host)
        h.hostname = str(data.get("hostname"))[:200]
        h.hb = {k: _clean(data.get(k)) for k in HB_FIELDS if k in data}
        h.last_seen = now
        mac = norm_mac(data.get("mac"))
        if mac:
            if h.mac and h.mac != mac and self.mac_host.get(h.mac) == host:
                self.mac_host.pop(h.mac, None)
            h.mac = mac
            self.mac_host[mac] = host
        if seen_ip:
            h.seen_ip = seen_ip
            self.ip_host[seen_ip] = host
        if not h.online:
            h.online, h.state_dirty, h.offline_reason = True, True, ""
        if data.get("dang_tat"):
            self.tat_sach[host] = now
        self.ui_changed.add(host)
        self.counters["hb"] += 1
        return host

    def mark_offline(self, host: str, reason: str) -> bool:
        h = self.hosts.get(norm_host(host))
        if h is None or not h.online:
            return False
        h.online, h.state_dirty, h.offline_reason = False, True, reason
        self.ui_changed.add(h.host)
        return True

    def is_online(self, host: str) -> bool:
        h = self.hosts.get(norm_host(host))
        return bool(h and h.online and self.clock() - h.last_seen <= OFFLINE_AFTER)

    def seen_within(self, host: str, seconds: float) -> bool:
        h = self.hosts.get(norm_host(host))
        return bool(h and self.clock() - h.last_seen <= seconds)

    def sweep(self) -> list[str]:
        """Máy quá OFFLINE_AFTER giây không nhịp tim → offline. Trả danh sách vừa chuyển offline."""
        cut = self.clock() - OFFLINE_AFTER
        gone = [h.host for h in self.hosts.values() if h.online and h.last_seen < cut]
        for host in gone:
            self.mark_offline(host, "mat_nhip_tim")
        return gone

    def online_hosts(self) -> list[str]:
        cut = self.clock() - OFFLINE_AFTER
        return [h.host for h in self.hosts.values() if h.online and h.last_seen >= cut]

    def host_for_mac(self, mac: str) -> str:
        return self.mac_host.get(norm_mac(mac), "")

    def host_for_ip(self, ip: str) -> str:
        return self.ip_host.get(ip or "", "")

    # ------------------------------------------------------------------ socket
    def register(self, host: str, sid: str) -> str:
        host = norm_host(host)
        if host:
            old = self.registered.get(host)
            if old and old != sid:
                self.sid_hosts.get(old, set()).discard(host)
            self.registered[host] = sid
            self.sid_hosts.setdefault(sid, set()).add(host)
        return host

    def unregister_sid(self, sid: str) -> list[str]:
        """Socket rớt: gỡ các máy mà sid này ĐANG giữ (máy đã nối lại bằng sid mới thì giữ nguyên)."""
        gone = []
        for host in self.sid_hosts.pop(sid, set()):
            if self.registered.get(host) == sid:
                self.registered.pop(host, None)
                gone.append(host)
        return gone

    def has_socket(self, host: str) -> bool:
        return norm_host(host) in self.registered

    def channel(self, host: str) -> str:
        """Kênh lệnh hiện có: 'socket' · 'http' (còn nhịp tim, mất socket) · 'none'."""
        if self.has_socket(host):
            return "socket"
        if self.is_online(host):
            return "http"
        return "none"

    # ------------------------------------------------------------------ hàng đợi HTTP /check_command/<mac>
    def enqueue(self, mac: str, cmd: Any) -> bool:
        mac = norm_mac(mac)
        if not mac:
            return False
        q = self.queue.setdefault(mac, deque())
        if len(q) >= QUEUE_MAX:
            q.popleft()
        q.append((self.clock(), cmd))
        return True

    def pop_command(self, mac: str) -> Any:
        """Lấy lệnh đầu hàng (FIFO). Lệnh quá QUEUE_TTL bị bỏ."""
        self.counters["poll"] += 1
        key = norm_mac(mac) or str(mac or "").lower()
        q = self.queue.get(key)
        if not q:
            return None
        cut = self.clock() - QUEUE_TTL
        while q:
            ts, cmd = q.popleft()
            if ts >= cut:
                if not q:
                    self.queue.pop(key, None)
                return cmd
        self.queue.pop(key, None)
        return None

    # ------------------------------------------------------------------ ACK
    def track(self, cid: str, host: str, mac: str, payload: dict) -> None:
        self.pending[cid] = {"host": norm_host(host), "mac": mac, "payload": payload, "ts": self.clock(), "tries": 1}

    def ack(self, cid: str) -> bool:
        return self.pending.pop(cid, None) is not None

    def due_retries(self) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
        """(cần gửi lại, bỏ cuộc). Đã gửi đủ ACK_MAX_TRIES lần hoặc máy mất socket → bỏ cuộc, KHÔNG chuyển hàng đợi
        HTTP: đường HTTP của agent không chống chạy đúp theo command_id (client.py 3922-3931) — có thể agent đã chạy
        lệnh, chỉ mất gói ACK."""
        now = self.clock()
        resend, failed = [], []
        for cid, info in list(self.pending.items()):
            if now - info["ts"] < ACK_TIMEOUT:
                continue
            if info["tries"] >= ACK_MAX_TRIES or not self.has_socket(info["host"]):
                self.pending.pop(cid, None)
                reason = "khong_ack" if info["tries"] >= ACK_MAX_TRIES else "mat_socket"
                if len(self.ack_failed) >= 2000:
                    self.ack_failed.pop(next(iter(self.ack_failed)))
                self.ack_failed[cid] = {"host": info["host"], "tries": info["tries"], "reason": reason, "ts": now}
                self.counters["ack_fail"] += 1
                failed.append((cid, info))
                continue
            info["tries"] += 1
            info["ts"] = now
            self.counters["ack_retry"] += 1
            resend.append((cid, info))
        return resend, failed

    # ------------------------------------------------------------------ cổng tải bộ cài
    def dl_acquire(self, max_concurrent: int, hold_seconds: float) -> bool:
        now = self.clock()
        cut = now - hold_seconds
        self.dl_slots[:] = [t for t in self.dl_slots if t > cut]  # slot tự hết hạn → không kẹt 503 (bài học 44')
        if len(self.dl_slots) >= max_concurrent:
            return False
        self.dl_slots.append(now)
        return True
