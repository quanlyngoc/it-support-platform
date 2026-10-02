"""Kiểm quyền theo catalog permissions + policy (đặc tả §75 bước 3)."""
from __future__ import annotations

from functools import wraps

from apiflask import abort

from app.tenants.context import current


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        current()
        return fn(*a, **kw)

    return wrapper


def require_perm(*codes: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            ctx = current()
            if not ctx.can(*codes):
                abort(403, "Không đủ quyền", extra_data={"code": "FORBIDDEN", "required": list(codes)})
            return fn(*a, **kw)

        return wrapper

    return deco
