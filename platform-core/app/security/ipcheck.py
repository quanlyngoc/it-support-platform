"""Giới hạn IP theo từng tài khoản (mang từ hệ cũ §8.4): danh sách rỗng = mọi nơi; có danh sách = NGHIÊM NGẶT."""
from __future__ import annotations

import ipaddress


def ip_allowed(ip: str | None, cidrs: list[str] | None) -> bool:
    if not cidrs:
        return True
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False  # bật giới hạn mà không đọc được IP -> chặn
    for c in cidrs:
        try:
            if addr in ipaddress.ip_network(c.strip(), strict=False):
                return True
        except ValueError:
            continue
    return False
