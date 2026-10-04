"""Định danh máy cho agent v2: chuẩn hoá MAC/tên máy, lọc serial rác, suy phòng từ tên máy.

Hàm THUẦN (không CSDL, không Flask) — chạy trong đường nhịp tim ≈ 440 lần/giây nên phải rẻ.
Nguồn hành vi (CHỈ ĐỌC): D:\\NetworkInventory\\utils.py `_room_from_hostname_raw`, `is_official_room`;
workers.py `generic_serials` (bài học 10.20: placeholder lọt vào đường định danh là mất máy thật).
"""
from __future__ import annotations

import re
from functools import lru_cache

# Giá trị tạm agent gửi vài giây đầu sau khởi động (HW nạp ở luồng nền) + serial rác của nhà sản xuất
PLACEHOLDERS = frozenset({"", "n/a", "...", "unknown", "none", "default", "null"})
GENERIC_SERIALS = PLACEHOLDERS | {"to be filled by o.e.m.", "oem", "default string", "0000000", "system serial number"}
MIN_SERIAL_LEN = 5  # Service Tag Dell thật = 7 ký tự; ngắn hơn 5 là rác

_HEX = re.compile(r"[^0-9a-f]")


def norm_host(hostname: object) -> str:
    """Khoá máy = tên máy VIẾT HOA (room socket `host_<HOST>` của hub cũ)."""
    return str(hostname or "").strip().upper()


def mac12(mac: object) -> str:
    """12 ký tự hex chữ thường, bỏ dấu phân cách; '' nếu không phải MAC hợp lệ."""
    s = _HEX.sub("", str(mac or "").lower())
    return s if len(s) == 12 else ""


def norm_mac(mac: object) -> str:
    """Dạng agent dùng ở /check_command/<mac>: chữ thường, phân cách ':'. '' nếu không hợp lệ."""
    s = mac12(mac)
    return ":".join(s[i:i + 2] for i in range(0, 12, 2)) if s else ""


def is_placeholder(value: object) -> bool:
    return str(value if value is not None else "").strip().lower() in PLACEHOLDERS


def valid_serial(serial: object) -> bool:
    s = str(serial or "").strip()
    return len(s) >= MIN_SERIAL_LEN and s.lower() not in GENERIC_SERIALS


@lru_cache(maxsize=8192)
def room_from_hostname_raw(hostname: str) -> str:
    """Phòng suy THUẦN từ tên máy (không xét chuyển phòng tay). Giữ y hệt hub cũ để số liệu khớp khi chạy song song."""
    if not hostname:
        return "Phòng chờ"
    name_u = str(hostname).upper()
    m1 = re.search(r"A6[-_]?(\d{3})", name_u)
    if m1:
        return f"Phòng {m1.group(1)} - A6"
    m2 = re.search(r"([A-Z]\d)[-_]?(\d{3})", name_u)
    if m2:
        return f"Phòng {m2.group(2)} - {m2.group(1)}"
    m3 = re.search(r"P(\d{3})", name_u)
    if m3:
        return f"Phòng {m3.group(1)}"
    junk = ("DESKTOP", "WIN", "LAPTOP", "PC", "ADMIN", "USER", "SV", "MAY")
    parts = re.split(r"[-_.]", name_u)
    if parts and len(parts[0]) >= 2:
        return "Phòng chờ" if parts[0].startswith(junk) else f"Khu vực {parts[0]}"
    return "Phòng chờ"


_RE_GV = re.compile(r"(^GV|-GV|_GV|\sGV|GV$|GIẢNG VIÊN|GIANG VIEN)")


def is_teacher_pc(hostname: object) -> bool:
    """Máy giảng viên — GIỐNG HỆT `is_teacher_pc` của hub cũ (app.py): lệnh cả phòng mặc định chừa máy GV ra."""
    return bool(hostname) and bool(_RE_GV.search(str(hostname).upper()))


def is_official_room(room: str) -> bool:
    """Phòng máy chính thức = 'Phòng <số>…' (loại Phòng chờ / Khu vực … khỏi tổng online)."""
    return bool(re.match(r"^Phòng\s+\d+", str(room or "").strip()))


def expected_host_for_seat(room: str, seat: object) -> str:
    """Tên máy CHUẨN của 1 vị trí: ('Phòng 301 - A6', 5) → 'A6-301-05'. Thiếu dữ kiện → '' (không tự gỡ được)."""
    m = re.match(r"^Phòng\s+(\d+)\s*-\s*(.+)$", str(room or "").strip())
    s = str(seat or "").strip()
    if not m or not s.isdigit():
        return ""
    return f"{m.group(2).strip().upper()}-{m.group(1)}-{int(s):02d}"


def host_matches_seat(hostname: str, room: str, seat: object) -> bool:
    """Tên máy đã khớp đúng vị trí được chuyển? Chấp nhận 'A6-301-5' lẫn 'A6-301-05' (utils.py host_matches_seat)."""
    exp = expected_host_for_seat(room, seat)
    if not exp:
        return False

    def norm(s: str) -> str:
        return re.sub(r"0+(\d)", r"\1", re.sub(r"[^A-Z0-9]", "-", str(s or "").upper()))

    return norm(hostname) == norm(exp)


def room_number(room_or_host: str) -> str:
    """Cụm 3 chữ số đầu tiên ('Phòng 405 - A6' / 'A6-405-12' → '405'); '' nếu không có."""
    m = re.search(r"\d{3}", str(room_or_host or ""))
    return m.group(0) if m else ""
