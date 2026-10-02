"""Điểm khởi chạy Platform-Core.

    uv run python -m app.server        (chạy thật: gevent + websocket)
Test dùng create_app(db=..., async_mode="threading") để không cần gevent.
"""
if __name__ == "__main__":  # PHẢI là câu lệnh đầu tiên: monkey-patch trước mọi import mạng/ssl/pymongo
    from gevent import monkey

    monkey.patch_all()

from apiflask import APIFlask  # noqa: E402
from flask.json.provider import DefaultJSONProvider  # noqa: E402

from app.config.settings import Settings, get_settings  # noqa: E402
from app.realtime.hub import socketio  # noqa: E402


def create_app(db=None, settings: Settings | None = None, async_mode: str | None = None,
               ldap_bind=None) -> APIFlask:
    s = settings or get_settings()
    app = APIFlask("platform-core", title="Platform-Core API", version=s.VERSION,
                   docs_path="/docs", spec_path="/openapi.json")
    if isinstance(app.json, DefaultJSONProvider):
        app.json.ensure_ascii = False  # trả tiếng Việt nguyên dạng, không \uXXXX
    app.config["ITM_SETTINGS"] = s
    app.config["ITM_LDAP_BIND"] = ldap_bind
    if db is None:
        from app.db.client import get_db

        db = get_db()
    app.extensions["itm_db"] = db

    from app.api.health import bp as health_bp
    from app.audit import hooks as audit_hooks
    from app.auth.routes import bp as auth_bp
    from app.auth.routes import load_context

    app.before_request(load_context)
    audit_hooks.register(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)

    mode = async_mode or s.ASYNC_MODE
    if mode not in ("gevent", "threading"):
        raise ValueError(f"ASYNC_MODE không hỗ trợ: {mode}")
    socketio.init_app(app, async_mode=mode, cors_allowed_origins=s.ALLOWED_ORIGINS)
    return app


def main() -> None:
    from app.utils.console import utf8_stdio

    utf8_stdio()
    s = get_settings()
    app = create_app()
    print(f"Platform-Core {s.VERSION} chạy cổng {s.PORT} (CSDL {s.MONGO_DB})")
    socketio.run(app, host="0.0.0.0", port=s.PORT)


if __name__ == "__main__":
    main()
