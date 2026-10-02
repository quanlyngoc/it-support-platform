"""Sự kiện Socket.IO agent v2 gửi lên (HOP_DONG mục E). Đăng ký trên đối tượng `socketio` dùng chung lúc import.

Khác hub cũ: KHÔNG broadcast. Kết quả chỉ về đúng trình duyệt đã hỏi (`reply_sid`) hoặc đúng room theo dõi máy của
tổ chức (`t:<tenant>:{ps|pty}:<mac12>`); thiếu địa chỉ thì bỏ, không phát cho tất cả.
"""
from __future__ import annotations

from flask import current_app, request
from flask_socketio import join_room

from app.legacy_adapter.adapter import LegacyAdapter
from app.realtime.hub import socketio
from app.utils.clientip import client_ip


def _ad() -> LegacyAdapter:
    return current_app.extensions["legacy"]


def _sid() -> str:
    return getattr(request, "sid", "")


def _data(d) -> dict:
    return d if isinstance(d, dict) else {}


@socketio.on("register")
def on_register(data=None):
    ad = _ad()
    if not ad.ip_ok(client_ip(request, ad.s.TRUSTED_PROXIES)):
        return
    host = ad.state.register(str(_data(data).get("hostname") or ""), _sid())
    if host:
        join_room(f"host_{host}")


@socketio.on("disconnect")
def on_disconnect(*_args):
    ad = _ad()
    for host in ad.state.unregister_sid(_sid()):
        ad.state.mark_offline(host, "mat_socket")  # socket rớt (kill agent / tắt máy) → offline NGAY như hub cũ


@socketio.on("cmd_ack")
def on_cmd_ack(data=None):
    cid = _data(data).get("command_id")
    if cid:
        _ad().state.ack(str(cid))


@socketio.on("client_update")
def on_client_update(data=None):
    ad = _ad()  # agent đời cũ gửi nhịp tim qua socket; 2.7.5.3 không còn gửi
    ad.state.ingest(_data(data), client_ip(request, ad.s.TRUSTED_PROXIES))


def _to_watchers(event: str, kind: str, data) -> None:
    d = _data(data)
    mac = d.get("mac")
    ad = _ad()
    if mac and ad.tenant_id:
        ad.emit(event, d, ad.room_dev(kind, str(mac)))


@socketio.on("client_ps_output")
def on_client_ps_output(data=None):
    _to_watchers("ps_output", "ps", data)


@socketio.on("client_pty_output")
def on_client_pty_output(data=None):
    _to_watchers("pty_output", "pty", data)


def _to_reply_sid(event: str, data) -> None:
    d = dict(_data(data))
    sid = d.pop("reply_sid", None)
    ad = _ad()
    # chỉ trả về trình duyệt; không cho agent "trả lời" vào socket của một agent khác
    if sid and isinstance(sid, str) and sid not in ad.state.sid_hosts:
        ad.emit(event, d, sid)


@socketio.on("fs_response")
def on_fs_response(data=None):
    _to_reply_sid("fs_response", data)


@socketio.on("fs_progress")
def on_fs_progress(data=None):
    _to_reply_sid("fs_progress", data)


@socketio.on("vnc_thumb")
def on_vnc_thumb(data=None):
    _to_reply_sid("vnc_thumb", data)
