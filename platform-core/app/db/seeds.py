"""Dữ liệu gốc: catalog quyền (đặc tả 4A.6) + quyền cho các tính năng đang chạy được giữ lại (C3)."""
from __future__ import annotations

from datetime import UTC, datetime

from pymongo.database import Database

PERMISSIONS: list[tuple[str, str]] = [
    ("user.view", "Xem người dùng"),
    ("user.edit", "Sửa người dùng"),
    ("user.delete", "Xoá người dùng"),
    ("user.toggle", "Bật/tắt người dùng"),
    ("local_user.create", "Tạo tài khoản Local"),
    ("local_user.delete", "Xoá tài khoản Local"),
    ("ad_user.add", "Thêm người dùng AD"),
    ("ad_user.delete", "Xoá người dùng AD"),
    ("policy.create", "Tạo policy"),
    ("policy.edit", "Sửa policy"),
    ("system.configure", "Cấu hình hệ thống"),
    ("backup.restore", "Sao lưu/khôi phục"),
    ("device.control", "Điều khiển máy"),
    ("room_map.edit", "Sửa sơ đồ phòng"),
    # Tính năng đang chạy ở hệ cũ, giữ lại (đặc tả V3 §1.3)
    ("agent.update", "Cập nhật agent theo đợt"),
    ("remote.vnc", "Xem/điều khiển màn hình (VNC)"),
    ("machine_events.view", "Xem nhật ký thay đổi máy"),
    ("audit.view", "Xem nhật ký hệ thống"),
]


def seed(db: Database) -> int:
    now = datetime.now(UTC)
    for code, name in PERMISSIONS:
        db.permissions.update_one(
            {"code": code},
            {"$set": {"name": name, "system": True, "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    return len(PERMISSIONS)
