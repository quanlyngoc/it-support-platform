"""Điều khiển từ xa (Sổ tay GĐ6): nguồn + Wake-on-LAN, đăng nhập từ xa, Internet, PowerShell / terminal hàng loạt.

Mọi lệnh đi qua bộ tương thích agent v2 (`LegacyAdapter.dispatch`: socket có ACK, mất socket thì hàng đợi HTTP có hạn),
KHÔNG broadcast; đích là máy cụ thể đã lọc theo phạm vi phòng của policy (như `_fs_may_touch` hệ cũ).
"""
