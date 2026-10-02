"""Phát hiện thay đổi phần cứng từ nhịp tim agent v2 → sự cố (incidents) tự động.

Quy tắc giữ y hệt hệ cũ (CHỈ ĐỌC: D:\\NetworkInventory\\utils.py `check_hardware_changes`):
- RAM: tổng `^(\\d+)GB` tăng → THÊM RAM · giảm → MẤT RAM · bằng nhau mà tập `[SN:…]` (bỏ SN chứa "0000") khác
  → TRÁO ĐỔI RAM.
- Ổ cứng: tổng các `(\\d+GB)` tăng/giảm/tráo SN tương tự.
- CMOS: chuỗi chứa "Hết pin" → cảnh báo hết pin CMOS.
Giá trị tạm "N/A" (agent mới khởi động) hoặc không đọc được dung lượng → KHÔNG so (bài học 10.20).
Hàm THUẦN — bộ ghi nền (writer.py) giữ giá trị cũ trong RAM và chỉ chạm CSDL khi thật sự có thay đổi.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from app.legacy_adapter.identity import is_placeholder

_RAM_TONG = re.compile(r"^(\d+)GB")
_DISK_GB = re.compile(r"\((\d+)GB\)")
_SN = re.compile(r"\[SN:(.*?)\]")


class ThayDoi(NamedTuple):
    loai: str       # hardware_ram | hardware_disk | cmos (dùng để chống tạo trùng sự cố đang chờ)
    tieu_de: str    # THÊM RAM / MẤT Ổ CỨNG / …
    mo_ta: str


def _sns(s: str) -> set[str]:
    return {x for x in _SN.findall(s) if "0000" not in x}


def _so_sanh(cu: str, moi: str, tong_cu: int, tong_moi: int, ten: str) -> str | None:
    if is_placeholder(cu) or is_placeholder(moi) or tong_cu <= 0 or tong_moi <= 0:
        return None
    if tong_moi > tong_cu:
        return f"THÊM {ten}"
    if tong_moi < tong_cu:
        return f"MẤT {ten}"
    sn_cu, sn_moi = _sns(cu), _sns(moi)
    if sn_cu and sn_moi and sn_cu != sn_moi:
        return f"TRÁO ĐỔI {ten}"
    return None


def tong_ram(s: str) -> int:
    m = _RAM_TONG.search(str(s or ""))
    return int(m.group(1)) if m else 0


def tong_disk(s: str) -> int:
    return sum(int(x) for x in _DISK_GB.findall(str(s or "")))


def ram_doi(cu: str, moi: str) -> ThayDoi | None:
    t = _so_sanh(str(cu or ""), str(moi or ""), tong_ram(cu), tong_ram(moi), "RAM")
    return ThayDoi("hardware_ram", t, f"{t}: {cu} -> {moi}") if t else None


def disk_doi(cu: str, moi: str) -> ThayDoi | None:
    t = _so_sanh(str(cu or ""), str(moi or ""), tong_disk(cu), tong_disk(moi), "Ổ CỨNG")
    return ThayDoi("hardware_disk", t, f"{t}: {cu} -> {moi}") if t else None


def het_pin_cmos(cmos: object) -> bool:
    return "Hết pin" in str(cmos or "")


CMOS = ThayDoi("cmos", "HẾT PIN CMOS", "CẢNH BÁO: HỆ THỐNG HẾT PIN CMOS (Giờ BIOS bị reset)")
