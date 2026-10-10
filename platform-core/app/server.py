"""Điểm khởi chạy Platform-Core.

    uv run python -m app.server        (chạy thật: gevent + websocket)
Test dùng create_app(db=..., async_mode="threading") để không cần gevent.
"""
if __name__ == "__main__":  # PHẢI là câu lệnh đầu tiên: monkey-patch trước mọi import mạng/ssl/pymongo
    from gevent import monkey

    monkey.patch_all()

import logging  # noqa: E402

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
    from app.storage import make_storage

    app.extensions["storage"] = make_storage(s.DATA_DIR)  # kho tệp chung (Sổ tay 7.1): <DATA_DIR>/tenants/<tid>/…

    from app.api import cors
    from app.api.desktop_release import bp as desktop_release_bp
    from app.api.health import bp as health_bp
    from app.audit import hooks as audit_hooks
    from app.auth.routes import bp as auth_bp
    from app.auth.routes import load_context
    from app.chat.routes import bp as chat_bp
    from app.control.routes import bp as control_bp
    from app.devices.routes import bp as devices_bp
    from app.devices.vnc import bp as vnc_bp
    from app.files.routes import bp as files_bp
    from app.incidents.routes import bp as incidents_bp
    from app.legacy_adapter import init_app as legacy_init
    from app.rooms.map_routes import bp as room_maps_bp
    from app.work.routes import bp as work_bp

    app.before_request(load_context)
    audit_hooks.register(app)
    cors.register(app, s.ALLOWED_ORIGINS)
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    legacy_init(app, db, s, socketio)
    app.register_blueprint(devices_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(room_maps_bp)
    app.register_blueprint(vnc_bp)
    app.register_blueprint(control_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(work_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(desktop_release_bp)
    from app.realtime import desktop  # noqa: F401  — đăng ký namespace /desktop lúc import

    mode = async_mode or s.ASYNC_MODE
    if mode not in ("gevent", "threading"):
        raise ValueError(f"ASYNC_MODE không hỗ trợ: {mode}")
    wildcard, origins = cors.parse(s.ALLOWED_ORIGINS)
    socketio.init_app(app, async_mode=mode, cors_allowed_origins="*" if wildcard else sorted(origins))
    return app


def _setup_logging() -> None:
    """INFO (tóm tắt SYNC 60 s…) → stdout = core-out.log; WARNING trở lên → stderr = core-err.log.
    Nhờ vậy "core-err.log có dòng mới" (Sổ tay 3.6/3.8) đúng nghĩa là có cảnh báo/lỗi."""
    import sys

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    out = logging.StreamHandler(sys.stdout)
    out.setLevel(logging.INFO)
    out.addFilter(lambda r: r.levelno < logging.WARNING)
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.WARNING)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (out, err):
        h.setFormatter(fmt)
    root.handlers[:] = [out, err]
    # gevent-websocket ghi MỌI request ở mức INFO (bỏ qua log_output) → ≈ 840 dòng/giây với 900 máy ≈ 10 GB/ngày
    # (đúng lỗi server.log phình GB của hub cũ). Chỉ giữ cảnh báo/lỗi.
    for noisy in ("geventwebsocket.handler", "engineio.server", "socketio.server"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _quiet_benign_warnings()


def _quiet_benign_warnings() -> None:
    """gevent cảnh báo "libuv only supports millisecond timer resolution" khi một lệnh chờ nhận thời gian < 1 ms (vd.
    "thời gian còn lại" khi phân giải DNS / nối Atlas lúc khởi động) — rồi tự làm tròn lên 1 ms, hoàn toàn vô hại.
    Xuất hiện NGẪU NHIÊN theo thời điểm (CapNhat 05/10/2026 dính một lần, các lần trước không) → báo động giả trong
    core-err.log như traceback Ctrl+C. Chỉ lọc ĐÚNG câu này của gevent; mọi cảnh báo khác vẫn ghi."""
    import warnings

    warnings.filterwarnings("ignore", message=r"libuv only supports millisecond timer resolution",
                            category=UserWarning, module=r"gevent\.")


def main() -> None:
    from app.utils.console import utf8_stdio

    utf8_stdio()
    _setup_logging()
    s = get_settings()
    app = create_app()
    app.extensions["legacy"].start()  # vòng nền: ghi computers theo lô + gửi lại lệnh chưa ACK
    from app.storage import sweeper

    sweeper.start(app, socketio)  # dọn kho tệp theo hạn, mỗi giờ
    from app.work import service as work

    work.start(app, socketio)  # tệp đã giao đang CHỜ XOÁ → xoá nốt khi máy online lại
    print(f"Platform-Core {s.VERSION} chạy {s.HOST}:{s.PORT} (CSDL {s.MONGO_DB})", flush=True)
    _quiet_ctrl_c()
    try:
        socketio.run(app, host=s.HOST, port=s.PORT)
    except KeyboardInterrupt:
        logging.getLogger("core").info("Dừng theo yêu cầu (NSSM stop / Ctrl+C)")


def _quiet_ctrl_c() -> None:
    """NSSM dừng dịch vụ bằng Ctrl+C → KeyboardInterrupt. gevent mặc định in ~30 dòng traceback ra stderr
    (core-err.log) mỗi lần dừng/CapNhat — báo động giả vì Sổ tay coi "core-err.log có dòng mới" là có lỗi.
    Thêm KeyboardInterrupt vào NOT_ERROR của hub: không in nữa, nhưng vẫn là SYSTEM_ERROR nên vẫn ném lên main
    để thoát (đã thử: tắt phần này thì stderr có traceback, bật thì stderr trống, mã thoát 0)."""
    from gevent import get_hub

    hub = get_hub()
    setattr(hub, "NOT_ERROR", (*getattr(hub, "NOT_ERROR", ()), KeyboardInterrupt))  # noqa: B010


if __name__ == "__main__":
    main()
