"""IP thật của client: Core đứng sau Caddy nên chỉ tin X-Forwarded-For khi request đến từ proxy tin cậy."""
from __future__ import annotations

from flask import Request


def client_ip_from_environ(environ: dict, trusted_proxies: tuple[str, ...]) -> str:
    remote = environ.get("REMOTE_ADDR") or ""
    xff = environ.get("HTTP_X_FORWARDED_FOR") or ""
    if remote in trusted_proxies and xff:
        return xff.split(",")[0].strip()
    return remote


def client_ip(request: Request, trusted_proxies: tuple[str, ...]) -> str:
    return client_ip_from_environ(request.environ, trusted_proxies)
