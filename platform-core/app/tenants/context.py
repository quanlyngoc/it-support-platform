"""Ngữ cảnh tổ chức của request (đặc tả §6.3): lấy từ phiên đã xác thực, KHÔNG BAO GIỜ từ dữ liệu client gửi."""
from __future__ import annotations

from dataclasses import dataclass, field

from bson import ObjectId
from flask import abort, g


@dataclass(frozen=True)
class Ctx:
    tenant_id: ObjectId
    tenant_code: str
    user_id: ObjectId
    username: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    room_ids: tuple[ObjectId, ...] = ()
    is_super: bool = False
    system: str = "LAB"
    session_id: ObjectId | None = None

    def can(self, *codes: str) -> bool:
        return self.is_super or set(codes) <= self.permissions


def optional() -> Ctx | None:
    return getattr(g, "ctx", None)


def current() -> Ctx:
    ctx = optional()
    if ctx is None:
        abort(401, "Chưa đăng nhập hoặc phiên đã hết hạn")
    return ctx
