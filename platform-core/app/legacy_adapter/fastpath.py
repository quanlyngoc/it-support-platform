"""Đường nhanh WSGI cho 2 route nóng nhất của agent v2: POST /update và GET /check_command/<mac>.

Hai route này là ≈ 95% lưu lượng agent (≈ 440 + ≈ 400 request/giây với ~900 máy). Đi thẳng vào LegacyAdapter, bỏ
qua Flask (định tuyến, before/after_request, đối tượng Request/Response). Đo 02/10/2026: 300 agent đi qua Flask tốn
≈ 28% một lõi → 900 agent vượt ngưỡng 50% của Sổ tay 3.3.

Logic nằm ở `LegacyAdapter.handle_update` / `handle_check_command`; test hợp đồng đi qua đúng lớp này vì test client
của Flask gọi `app.wsgi_app`.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

from app.utils.clientip import client_ip_from_environ

log = logging.getLogger("legacy.fastpath")
MAX_BODY = 256 * 1024  # nhịp tim thật ≈ 1 KB
_CMD = "/check_command/"


class FastPath:
    def __init__(self, inner: Callable, adapter: Any, trusted_proxies: tuple[str, ...]):
        self.inner = inner
        self.ad = adapter
        self.trusted = trusted_proxies
        self._last_err = 0.0

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        path = environ.get("PATH_INFO") or ""
        method = environ.get("REQUEST_METHOD")
        if method == "POST" and path == "/update":
            return self._update(environ, start_response)
        if method == "GET" and path.startswith(_CMD) and len(path) > len(_CMD):
            return self._check_command(environ, start_response, path[len(_CMD):])
        return self.inner(environ, start_response)

    @staticmethod
    def _json(start_response: Callable, obj: dict, status: str = "200 OK") -> list[bytes]:
        body = json.dumps(obj, ensure_ascii=False).encode()
        start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        return [body]

    def _update(self, environ: dict, start_response: Callable) -> list[bytes]:
        out: dict = {"status": "success"}
        try:
            n = int(environ.get("CONTENT_LENGTH") or 0)
            raw = environ["wsgi.input"].read(min(n, MAX_BODY)) if n > 0 else b""
            try:
                data = json.loads(raw) if raw else {}
            except ValueError:
                data = {}
            out = self.ad.handle_update(data if isinstance(data, dict) else {},
                                        client_ip_from_environ(environ, self.trusted))
        except Exception:
            now = time.monotonic()
            if now - self._last_err >= 60:  # tối đa 1 dòng/60 s — không để nhật ký phình
                self._last_err = now
                log.exception("Lỗi xử lý /update (vẫn trả 200 — luật A1)")
        return self._json(start_response, out)  # LUÔN 200 (A1)

    def _check_command(self, environ: dict, start_response: Callable, mac: str) -> list[bytes]:
        if not self.ad.ip_ok(client_ip_from_environ(environ, self.trusted)):
            return self._json(start_response, {"status": "error", "message": "IP không thuộc dải agent"},
                              "403 FORBIDDEN")
        return self._json(start_response, self.ad.handle_check_command(mac))
