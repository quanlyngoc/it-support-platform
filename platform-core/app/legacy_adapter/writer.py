"""Bộ ghi nền: đưa trạng thái RAM xuống MongoDB theo lô (Sổ tay 3.3; luật A10).

- `computers`: ghi khi máy ĐỔI trạng thái (online/offline) ở nhịp kế, còn lại 60 s/lần/máy — thay cho hub cũ ghi
  MỖI nhịp tim (≈ 440 lần/s, quá sức Atlas RTT 55 ms). Upsert theo `legacy_hostname`; KHÔNG BAO GIỜ xoá máy.
- Giá trị tạm lúc khởi động ("N/A", "...") không đè dữ liệu thật đã có (bài học 10.20).
- `machine_events` (bất biến, chỉ thêm) + `computers_archive` khi phát hiện tráo phần cứng (bài học 10.21):
    trao_phan_cung = máy KHÁC TÊN mà trùng MAC/serial (máy kia đã tắt > 90 s; còn bật song song = ANTI-GHOST, bỏ qua)
    doi_serial / doi_mac = CÙNG tên mà serial/MAC đổi. Chống ghi lặp 6 giờ/tình huống.
- `usage_stats`: +1 phút/máy online mỗi 60 s.
Nguồn hành vi (CHỈ ĐỌC): D:\\NetworkInventory\\workers.py `async_db_writer_worker`, `_mevt_swap`, `_mevt_hwid`.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.database import Database

from app.legacy_adapter.hardware import CMOS, ThayDoi, disk_doi, het_pin_cmos, ram_doi
from app.legacy_adapter.identity import is_placeholder, mac12, room_from_hostname_raw, valid_serial
from app.legacy_adapter.state import Host, LegacyState
from app.tenants.repo import repo_for

log = logging.getLogger("legacy.writer")

SNAPSHOT_EVERY = 60.0
MAX_WRITES_PER_TICK = 200   # trần mỗi nhịp 2 s (máy đổi trạng thái được ưu tiên)
MAX_SNAPSHOTS_PER_TICK = 60  # ghi định kỳ: cần ≈ 30/nhịp với 900 máy → dư gấp đôi, giãn đều thay vì dồn cục 60 s
USAGE_EVERY = 60.0
ANTI_GHOST = 90.0
MEVT_TTL = 6 * 3600.0
_HW_TEXT = ("cpu", "ram", "mainboard", "disk", "model", "network", "cmos_battery", "cpu_temp", "cpu_fan",
            "client_version", "ip")
_USAGE_NUM = ("cpu_usage", "ram_usage", "disk_usage")


class Writer:
    def __init__(self, db: Database, tenant_id: ObjectId, state: LegacyState, *,
                 today: Callable[[], str] = lambda: datetime.now().strftime("%Y-%m-%d")):
        self.state = state
        self.today = today
        self.computers = repo_for(db, tenant_id, "computers")
        self.events = repo_for(db, tenant_id, "machine_events")
        self.archive = repo_for(db, tenant_id, "computers_archive")
        self.usage = repo_for(db, tenant_id, "usage_stats")
        self.incidents = repo_for(db, tenant_id, "incidents")
        self.hwid: dict[str, tuple[str, str]] = {}      # HOST → (serial hợp lệ cuối, mac12)
        self.serial_owner: dict[str, set[str]] = {}
        self.mac_owner: dict[str, set[str]] = {}
        self.ids: dict[str, ObjectId] = {}
        self.overrides: dict[str, str] = {}             # HOST → phòng ép tay (computers.room_override)
        self._mevt_seen: dict[tuple, float] = {}
        self.hw_last: dict[str, tuple[str, str]] = {}   # HOST → (ram, disk) thật lần trước — so trong RAM
        self.cmos_bao: dict[str, bool] = {}              # HOST → đang báo hết pin CMOS (chỉ xét lúc chuyển trạng thái)
        self.on_incident: Callable[[dict], object] | None = None  # adapter gắn để phát realtime cho Desktop
        self.primed = False
        self.last_usage = state.clock()

    # ------------------------------------------------------------------ nạp nền so sánh
    def prime(self) -> int:
        """Nạp 1 lần lúc khởi động: thiếu bước này thì tráo phần cứng xảy ra TRONG lúc Core tắt sẽ lọt lưới."""
        n = 0
        for d in self.computers.find({"legacy_hostname": {"$type": "string"}},
                                     {"legacy_hostname": 1, "serial": 1, "mac": 1, "room_override": 1, "ram": 1,
                                      "disk": 1}):
            host = d["legacy_hostname"]
            self.ids[host] = d["_id"]
            self._remember(host, str(d.get("serial") or "") if valid_serial(d.get("serial")) else "",
                           mac12(d.get("mac")))
            if d.get("room_override"):
                self.overrides[host] = str(d["room_override"])
            if d.get("ram") or d.get("disk"):
                self.hw_last[host] = (str(d.get("ram") or ""), str(d.get("disk") or ""))
            n += 1
        self.primed = True
        return n

    def room_of(self, host: str, hostname: str = "") -> str:
        return self.overrides.get(host) or room_from_hostname_raw(hostname or host)

    # ------------------------------------------------------------------ nhịp ghi
    def tick(self) -> int:
        """Một nhịp (gọi mỗi 2 s): quét offline, ghi lô `computers`, cộng phút sử dụng. Trả số máy đã ghi."""
        if not self.primed:
            self.prime()
        self.state.sweep()
        now = self.state.clock()
        hosts = self.state.hosts.values()
        changed = [h for h in hosts if h.state_dirty][:MAX_WRITES_PER_TICK]
        due = sorted((h for h in hosts if not h.state_dirty and h.online and now - h.written_at >= SNAPSHOT_EVERY),
                     key=lambda h: h.written_at)
        batch = changed + due[:max(0, min(MAX_SNAPSHOTS_PER_TICK, MAX_WRITES_PER_TICK - len(changed)))]
        if batch:
            for h in batch:
                if h.online:
                    self._identity(h)
                    self._hardware(h)
            self.computers.bulk_upsert([self._upsert(h) for h in batch])
            for h in batch:  # chỉ hạ cờ SAU khi ghi thành công — Atlas lỗi thì nhịp sau ghi lại
                h.state_dirty, h.written_at = False, now
        if now - self.last_usage >= USAGE_EVERY:
            self.last_usage = now
            self._usage()
        return len(batch)

    def _upsert(self, h: Host) -> tuple[dict, dict]:
        dt = datetime.now(UTC)
        hb = h.hb
        s: dict = {"hostname": h.hostname or h.host, "legacy_hostname": h.host, "is_online": h.online,
                   "room_name": self.room_of(h.host, h.hostname), "source": "agent_v2", "updated_at": dt}
        for k in _HW_TEXT:
            if k in hb and not is_placeholder(hb[k]):
                s[k] = hb[k]
        if not is_placeholder(hb.get("serial")):
            s["serial"] = hb["serial"]
        if h.mac:
            s["mac"] = h.mac
        if h.seen_ip:
            s["seen_ip"] = h.seen_ip
        if h.online:
            for k in _USAGE_NUM:
                if k in hb:
                    s[k] = hb[k]
            s["last_heartbeat_at"] = datetime.fromtimestamp(h.last_seen, UTC)
        else:
            s["offline_at"] = dt
            s["offline_reason"] = h.offline_reason
        return {"legacy_hostname": h.host}, {"$set": s, "$setOnInsert": {"created_at": dt}}

    # ------------------------------------------------------------------ định danh phần cứng (A10)
    def _remember(self, host: str, serial: str, mac: str) -> None:
        old = self.hwid.get(host)
        if old:
            if old[0]:
                self.serial_owner.get(old[0].upper(), set()).discard(host)
            if old[1]:
                self.mac_owner.get(old[1], set()).discard(host)
        self.hwid[host] = (serial, mac)
        if serial:
            self.serial_owner.setdefault(serial.upper(), set()).add(host)
        if mac:
            self.mac_owner.setdefault(mac, set()).add(host)

    def _identity(self, h: Host) -> None:
        raw_serial = str(h.hb.get("serial") or "").strip()
        serial = raw_serial if valid_serial(raw_serial) else ""
        mac = mac12(h.mac)
        # Vế 1 — máy KHÁC TÊN mang cùng phần cứng (ổ cứng máy này đã lắp vào thân máy kia)
        other, by = "", ""
        if mac:
            others = self.mac_owner.get(mac, set()) - {h.host}
            if others:
                other, by = sorted(others)[0], "MAC"
        if not other and serial:
            others = self.serial_owner.get(serial.upper(), set()) - {h.host}
            if others:
                other, by = sorted(others)[0], "Service Tag"
        if other:
            if self.state.seen_within(other, ANTI_GHOST):
                log.debug("ANTI-GHOST: %s và %s trùng %s nhưng đang bật song song", h.host, other, by)
            else:
                self._swap(h.host, other, by)
        # Vế 2 — CÙNG tên mà serial/MAC đổi (ổ cứng này đã sang thân máy khác / thay main / card mạng)
        old = self.hwid.get(h.host)
        if old:
            if serial and old[0] and old[0] != serial:
                self._mevt(h.host, "doi_serial", field="serial", old=old[0], new=serial,
                           note=f"{h.host} đổi Service Tag {old[0]} -> {serial}: ổ cứng đã sang thân máy khác, "
                                f"hoặc thân máy này được thay bo mạch chủ.")
            if mac and old[1] and old[1] != mac:
                self._mevt(h.host, "doi_mac", field="mac", old=old[1], new=mac,
                           note=f"{h.host} đổi MAC {old[1]} -> {mac}: đổi card mạng hoặc đổi thân máy.")
        self._remember(h.host, serial or (old[0] if old else ""), mac or (old[1] if old else ""))

    def _mevt(self, host: str, event: str, *, matched_by: str = "", other: str = "", field: str = "",
              old: str = "", new: str = "", note: str = "") -> bool:
        key = (host, event, other, old, new)
        now = self.state.clock()
        if now - self._mevt_seen.get(key, -1e18) < MEVT_TTL:
            return False
        if len(self._mevt_seen) > 5000:
            self._mevt_seen.clear()
        self._mevt_seen[key] = now
        self.events.insert_one({"hostname": host, "event": event, "matched_by": matched_by, "other_host": other,
                                "field": field, "old_value": old, "new_value": new, "action": "giu_nguyen",
                                "note": note, "created_at": datetime.now(UTC)})
        log.warning("MAY %s: %s", host, note or event)
        return True

    def _swap(self, new_host: str, old_host: str, by: str) -> None:
        note = (f"{new_host} báo trùng {by} với {old_host}. Rất có thể ổ cứng của {new_host} đã được lắp vào thân "
                f"máy của {old_host} (hoặc máy cũ cài lại & đổi tên). ĐÃ GIỮ NGUYÊN cả hai dòng — admin kiểm rồi "
                f"tự xử lý (Xoá máy / Chuyển phòng).")
        if not self._mevt(new_host, "trao_phan_cung", matched_by=by, other=old_host, note=note):
            return
        doc = self.computers.find_one({"legacy_hostname": old_host})
        if doc:
            snap = {k: v for k, v in doc.items() if k not in ("_id", "tenant_id")}
            self.archive.insert_one({**snap, "original_id": doc["_id"], "archived_at": datetime.now(UTC),
                                     "reason": f"trung {by} voi {new_host}"})

    # ------------------------------------------------------------------ thay đổi phần cứng → sự cố
    def _hardware(self, h: Host) -> None:
        """RAM / ổ cứng đổi hoặc hết pin CMOS → sự cố PENDING (quy tắc của hệ cũ, xem hardware.py).
        So trong RAM; chỉ chạm CSDL khi THẬT SỰ có thay đổi (hệ cũ truy vấn mỗi nhịp tim)."""
        ram, disk = str(h.hb.get("ram") or ""), str(h.hb.get("disk") or "")
        cu = self.hw_last.get(h.host)
        if cu:
            for td in (ram_doi(cu[0], ram), disk_doi(cu[1], disk)):
                if td:
                    self._incident(h, td)
        self.hw_last[h.host] = (ram if not is_placeholder(ram) else (cu[0] if cu else ""),
                                disk if not is_placeholder(disk) else (cu[1] if cu else ""))
        het = het_pin_cmos(h.hb.get("cmos_battery"))
        if het and not self.cmos_bao.get(h.host):
            self._incident(h, CMOS)
        self.cmos_bao[h.host] = het

    def _incident(self, h: Host, td: ThayDoi) -> bool:
        """Tạo sự cố, trừ khi máy đã có sự cố CÙNG LOẠI đang chờ/đang xử lý (chống trùng như hệ cũ)."""
        dang_mo = {"$in": ["PENDING", "PROCESSING"]}
        if self.incidents.count({"hostname": h.host, "category": td.loai, "status": dang_mo}):
            return False
        doc = {"hostname": h.host, "device_id": self.ids.get(h.host), "room_name": self.room_of(h.host, h.hostname),
               "title": td.tieu_de, "description": td.mo_ta[:2000], "category": td.loai, "status": "PENDING",
               "source": "SYSTEM_WATCHDOG", "reporter_name": "SYSTEM_WATCHDOG", "created_at": datetime.now(UTC)}
        self.incidents.insert_one(doc)
        log.warning("SU-CO %s: %s", h.host, td.tieu_de)
        if self.on_incident:
            self.on_incident({"hostname": h.host, "room_name": doc["room_name"], "title": td.tieu_de,
                              "description": doc["description"], "created_at": doc["created_at"].isoformat()})
        return True

    # ------------------------------------------------------------------ phút sử dụng
    def _usage(self) -> None:
        hosts = self.state.online_hosts()
        if not hosts:
            return
        missing = [h for h in hosts if h not in self.ids]
        if missing:
            for d in self.computers.find({"legacy_hostname": {"$in": missing}}, {"legacy_hostname": 1}):
                self.ids[d["legacy_hostname"]] = d["_id"]
        day, dt = self.today(), datetime.now(UTC)
        items = []
        for host in hosts:
            did = self.ids.get(host)
            if did is None:
                continue  # chưa kịp có dòng computers — phút này bỏ qua
            h = self.state.hosts[host]
            items.append(({"device_id": did, "date": day},
                          {"$inc": {"online_minutes": 1},
                           "$set": {"hostname": h.hostname or host, "room_name": self.room_of(host, h.hostname),
                                    "updated_at": dt}}))
        self.usage.bulk_upsert(items)


def run_forever(tick: Callable[[], object], sleep: Callable[[float], object], every: float, name: str) -> None:
    """Vòng nền bền: lỗi một nhịp (vd. Atlas chập chờn) chỉ ghi nhật ký rồi chạy tiếp, không bao giờ chết."""
    while True:
        sleep(every)
        t0 = time.monotonic()
        try:
            tick()
        except Exception:
            log.exception("Vòng nền %s lỗi (sẽ thử lại nhịp sau)", name)
        if time.monotonic() - t0 > max(every, 5.0):
            log.warning("Vòng nền %s chậm: %.1f s", name, time.monotonic() - t0)
