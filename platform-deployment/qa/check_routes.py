"""Kiểm trùng route/endpoint/socket handler của Platform-Core (py_compile không bắt được — bài học hệ cũ §3.6).

    uv run --project platform-core python platform-deployment/qa/check_routes.py
Dựng app trên mongomock (không cần CSDL thật). Thoát mã 0 = đạt.
"""
from __future__ import annotations

import collections
import pathlib
import sys

CORE = pathlib.Path(__file__).resolve().parents[2] / "platform-core"
sys.path.insert(0, str(CORE))


def main() -> int:
    import mongomock

    from app.config.settings import Settings
    from app.realtime.hub import socketio
    from app.server import create_app

    try:
        app = create_app(db=mongomock.MongoClient()["qa"], settings=Settings(MONGO_URI="mongodb://khong-dung"),
                         async_mode="threading")
    except AssertionError as e:  # Flask nổ khi 2 view khác nhau cùng tên endpoint
        print("[ROUTE] trùng endpoint:", e)
        return 1

    bad = 0
    seen: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for rule in app.url_map.iter_rules():
        for m in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            seen[(rule.rule, m)].append(rule.endpoint)
    for (path, method), eps in sorted(seen.items()):
        if len(eps) > 1:
            print(f"[ROUTE] {method} {path} khai báo {len(eps)} lần: {', '.join(eps)}")
            bad += 1

    # Socket handler: Flask-SocketIO giữ danh sách (event, namespace); trùng = cái sau đè cái trước, im lặng
    handlers = collections.Counter((h[0], h[2]) for h in getattr(socketio, "handlers", []))
    for (event, ns), n in handlers.items():
        if n > 1:
            print(f"[SOCKET] '{event}' (namespace {ns or '/'}) đăng ký {n} lần")
            bad += 1

    n_routes = len(seen)
    print(f"check_routes: {n_routes} route+method, {len(handlers)} socket handler —",
          "ĐẠT" if not bad else f"{bad} lỗi")
    return 1 if bad else 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        getattr(s, "reconfigure", lambda **_: None)(encoding="utf-8", errors="replace")
    raise SystemExit(main())
