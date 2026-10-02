"""IP thật của client: Core đứng sau Caddy nên chỉ tin X-Forwarded-For khi request đến từ proxy tin cậy."""
from __future__ import annotations

from flask import Request


def client_ip(request: Request, trusted_proxies: tuple[str, ...]) -> str:
    remote = request.remote_addr or ""
    xff = request.headers.get("X-Forwarded-For", "")
    if remote in trusted_proxies and xff:
        return xff.split(",")[0].strip()
    return remote
