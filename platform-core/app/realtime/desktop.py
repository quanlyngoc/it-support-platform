"""Kênh realtime cho Desktop — namespace Socket.IO `/desktop` (Sổ tay 4.5, 5.4, GĐ6).

TÁCH HẲN namespace `/` của agent v2: agent không gọi được sự kiện của Desktop và ngược lại.
- Kết nối PHẢI mang token đăng nhập (`auth: {token}`); thiếu/sai → từ chối. MỖI sự kiện kiểm lại token (đệm 15 s của
  auth_service) → đăng xuất / bị đá phiên (1 thiết bị) / khoá tài khoản là mất quyền ngay, socket bị ngắt.
- Room luôn mang mã tổ chức (`t:<tenant_id>:…`) — người của tổ chức này không nghe được tổ chức khác.
- Tự vào `t:<tid>:devices` (số đếm toàn trường) + `t:<tid>:incidents` nếu policy KHÔNG giới hạn phòng; người bị giới hạn
  phòng chỉ đăng ký được các phòng của mình.
- Điều khiển (terminal / PowerShell / trình duyệt tệp / ảnh màn hình) chuyển tới ĐÚNG máy qua bộ tương thích agent v2,
  kiểm quyền `device.control` / `remote.vnc` + phạm vi phòng. Hệ cũ broadcast mấy đường này — Core thì không.
Mọi handler trả "ack" `{ok: bool, error?: str}` để Desktop hiện lỗi rõ ràng.
"""
from __future__ import annotations

import re
from typing import Any

from flask import current_app, request
from flask_socketio import disconnect, join_room, leave_room
from socketio.exceptions import ConnectionRefusedError

from app.auth import service as auth_service
from app.devices import service as devices
from app.legacy_adapter.identity import mac12
from app.realtime.hub import DESKTOP_NS, socketio
from app.tenants.context import Ctx

_TOKENS: dict[str, str] = {}  # sid (namespace /desktop) → token Bearer — một tiến trình Core duy nhất


def _db():
    return current_app.extensions["itm_db"]


def _ad():
    return current_app.extensions.get("legacy")


def _sid() -> str:
    return getattr(request, "sid", "")


def _ctx() -> Ctx | None:
    ctx = auth_service.resolve(_db(), _TOKENS.get(_sid()))
    if ctx is None:
        _TOKENS.pop(_sid(), None)
        disconnect()
    return ctx


def _unrestricted(ctx: Ctx) -> bool:
    return ctx.is_super or not ctx.room_ids


def _err(msg: str) -> dict:
    return {"ok": False, "error": msg}


def user_room(ctx: Ctx) -> str:
    return f"t:{ctx.tenant_id}:u:{ctx.user_id}"


@socketio.on("connect", namespace=DESKTOP_NS)
def on_connect(auth=None):
    token = auth.get("token") if isinstance(auth, dict) else None
    ctx = auth_service.resolve(_db(), token if isinstance(token, str) else None)
    if ctx is None:
        raise ConnectionRefusedError("Chưa đăng nhập hoặc phiên đã hết hạn")
    _TOKENS[_sid()] = str(token)
    join_room(user_room(ctx))  # kết quả lệnh chỉ dành cho người bấm (đăng nhập từ xa…)
    if _unrestricted(ctx):
        join_room(f"t:{ctx.tenant_id}:devices")
        join_room(f"t:{ctx.tenant_id}:incidents")
    return True


@socketio.on("disconnect", namespace=DESKTOP_NS)
def on_disconnect(*_args):
    _TOKENS.pop(_sid(), None)


# ====================================================================== đăng ký nghe
@socketio.on("subscribe_room", namespace=DESKTOP_NS)
def subscribe_room(data=None):
    ctx = _ctx()
    if ctx is None:
        return _err("Phiên đã hết hạn")
    rid = str((data or {}).get("room_id") or "")
    if devices.get_room(_db(), ctx, None, rid) is None:  # kiểm cả tổ chức lẫn phạm vi phòng của policy
        return _err("Không có phòng này hoặc ngoài phạm vi được giao")
    join_room(f"t:{ctx.tenant_id}:room:{rid}")
    return {"ok": True}


@socketio.on("unsubscribe_room", namespace=DESKTOP_NS)
def unsubscribe_room(data=None):
    ctx = _ctx()
    if ctx is None:
        return _err("Phiên đã hết hạn")
    leave_room(f"t:{ctx.tenant_id}:room:{(data or {}).get('room_id')}")
    return {"ok": True}


@socketio.on("subscribe_result", namespace=DESKTOP_NS)
def subscribe_result(data=None):
    """Nghe kết quả bất đồng bộ theo token (PowerShell hàng loạt, giao/thu bài) — kèm poll /api/legacy/results."""
    ctx = _ctx()
    if ctx is None:
        return _err("Phiên đã hết hạn")
    if not ctx.can("device.control"):
        return _err("Không đủ quyền")
    tok = str((data or {}).get("token") or "")
    if not tok.isalnum():
        return _err("Token không hợp lệ")
    join_room(f"t:{ctx.tenant_id}:res:{tok.lower()}")
    return {"ok": True}


def _target(ctx: Ctx, data: Any, perm: str) -> tuple[Any, dict] | dict:
    """Máy đích của một thao tác điều khiển: kiểm quyền + phạm vi + máy thuộc agent v2 đang được Core quản."""
    if not ctx.can(perm):
        return _err("Không đủ quyền")
    d = devices.get_device(_db(), ctx, _ad(), str((data or {}).get("device_id") or ""))
    ad = _ad()
    if d is None or ad is None or ad.tenant_id != ctx.tenant_id:
        return _err("Không có máy này hoặc ngoài phạm vi được giao")
    return ad, d


@socketio.on("watch_device", namespace=DESKTOP_NS)
def watch_device(data=None):
    """Nghe luồng của 1 máy: kind = ps (PowerShell) | pty (terminal) | watch (kết quả đăng nhập từ xa)."""
    ctx = _ctx()
    if ctx is None:
        return _err("Phiên đã hết hạn")
    kind = str((data or {}).get("kind") or "")
    if kind not in ("ps", "pty", "watch"):
        return _err("kind phải là ps | pty | watch")
    t = _target(ctx, data, "device.control")
    if isinstance(t, dict):
        return t
    ad, d = t
    if not d.get("mac"):
        return _err("Máy chưa có MAC")
    join_room(ad.room_dev(kind, d["mac"]))
    return {"ok": True}


@socketio.on("unwatch_device", namespace=DESKTOP_NS)
def unwatch_device(data=None):
    ctx = _ctx()
    if ctx is None:
        return _err("Phiên đã hết hạn")
    kind = str((data or {}).get("kind") or "")
    mac = str((data or {}).get("mac") or "")
    if kind in ("ps", "pty", "watch") and mac12(mac):
        leave_room(f"t:{ctx.tenant_id}:{kind}:{mac12(mac)}")
    return {"ok": True}


# ====================================================================== điều khiển → đúng máy
def _send(perm: str, data: Any, fn) -> dict:
    ctx = _ctx()
    if ctx is None:
        return _err("Phiên đã hết hạn")
    t = _target(ctx, data, perm)
    if isinstance(t, dict):
        return t
    ad, d = t
    host = str(d.get("hostname") or "").upper()
    if not fn(ad, host, d):
        return _err("Máy không còn kênh socket (đang tắt hoặc mất kết nối)")
    return {"ok": True}


@socketio.on("pty_input", namespace=DESKTOP_NS)
def pty_input(data=None):
    return _send("device.control", data, lambda ad, host, d: ad.send_to_host(
        "server_pty_input", {"mac": d.get("mac", ""), "hostname": host, "data": str((data or {}).get("data") or "")},
        host))


@socketio.on("pty_resize", namespace=DESKTOP_NS)
def pty_resize(data=None):
    def go(ad, host, d):
        cols, rows = int((data or {}).get("cols") or 120), int((data or {}).get("rows") or 30)
        return ad.send_to_host("server_pty_resize", {"mac": d.get("mac", ""), "hostname": host,
                                                     "cols": max(10, min(cols, 500)), "rows": max(5, min(rows, 200))},
                               host)
    return _send("device.control", data, go)


@socketio.on("ps_input", namespace=DESKTOP_NS)
def ps_input(data=None):
    return _send("device.control", data, lambda ad, host, d: ad.send_ps_input(d.get("mac", ""),
                                                                              str((data or {}).get("data") or "")))


_FS_KEYS = ("op", "req_id", "path", "target", "src", "dst", "name", "token", "folder", "filename", "unzip",
            "download_url")
_FS_OPS = ("list", "mkdir", "delete", "rename", "pull", "push", "copy", "recycle")
# push: agent tải `{UPDATE_URL}{download_url}` → CHỈ cho 2 đường tệp theo token (hub cũ để trình duyệt truyền tuỳ ý)
_FS_DL = re.compile(r"^/fs_(?:serve|bridge)/([0-9a-f]{8,64})$")


def _fs_token_ok(ctx: Ctx, data: dict) -> str:
    """pull/push phải mang token truyền tệp CÒN HẠN của đúng tổ chức (cấp qua /api/files/*). Lỗi → thông báo."""
    op = data.get("op")
    if op not in ("pull", "push"):
        return ""
    ad = _ad()
    store = ad.store() if ad is not None and ad.tenant_id == ctx.tenant_id else None
    if op == "push":
        m = _FS_DL.match(str(data.get("download_url") or ""))
        tok = m.group(1) if m else ""
    else:
        tok = str(data.get("token") or "")
    if store is None or not tok or store.fs_token(tok) is None:
        return "Token truyền tệp sai hoặc đã hết hạn — xin token mới qua /api/files"
    return ""


@socketio.on("fs_request", namespace=DESKTOP_NS)
def fs_request(data=None):
    """Trình duyệt tệp: chỉ chuyển các khoá đã biết; reply_sid do SERVER gắn (không tin Desktop) → về đúng sid."""
    op = str((data or {}).get("op") or "")
    if op not in _FS_OPS:
        return _err("op không hợp lệ")
    body = {k: (data or {})[k] for k in _FS_KEYS if k in (data or {})}
    ctx = _ctx()
    if ctx is None:
        return _err("Phiên đã hết hạn")
    if msg := _fs_token_ok(ctx, body):
        return _err(msg)
    return _send("device.control", data, lambda ad, host, d: ad.send_fs_request(host, body, _sid()))


@socketio.on("vnc_thumb_req", namespace=DESKTOP_NS)
def vnc_thumb_req(data=None):
    return _send("remote.vnc", data, lambda ad, host, d: ad.send_vnc_thumb_req(host, _sid(),
                                                                              bool((data or {}).get("hd"))))
