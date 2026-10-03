"""CORS cho API Desktop (/api/*, /openapi.json).

Desktop (Tauri 2 / WebView2) chạy ở origin `http://tauri.localhost` (bản cài) hoặc `http://localhost:1420`
(pnpm tauri dev) — khác origin của Core nên trình duyệt nhúng chặn request mang header Authorization nếu Core không
trả header CORS.
Xác thực bằng header Bearer (KHÔNG cookie) nên không dùng Allow-Credentials. Route agent v2 (/update…) không liên quan.
`ALLOWED_ORIGINS`: "*" (dựng thử — HOAN_BAO_MAT) hoặc danh sách cách nhau bằng dấu phẩy.
"""
from __future__ import annotations

from flask import Flask, make_response, request

_PATHS = ("/api/", "/openapi.json")


def parse(allowed: str) -> tuple[bool, frozenset[str]]:
    items = {o.strip().rstrip("/") for o in str(allowed or "").split(",") if o.strip()}
    return "*" in items, frozenset(items - {"*"})


def register(app: Flask, allowed: str) -> None:
    wildcard, origins = parse(allowed)

    def ok(origin: str | None) -> bool:
        return bool(origin) and (wildcard or origin.rstrip("/") in origins)

    @app.before_request
    def _preflight():
        if request.method == "OPTIONS" and request.path.startswith(_PATHS):
            return make_response("", 204)  # after_request bên dưới gắn header
        return None

    @app.after_request
    def _cors(resp):
        origin = request.headers.get("Origin")
        if request.path.startswith(_PATHS) and ok(origin):
            resp.headers["Access-Control-Allow-Origin"] = str(origin)
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
            resp.headers["Access-Control-Max-Age"] = "600"
            resp.vary.add("Origin")
        return resp
