"""Bộ chạy test hợp đồng agent v2 (tests/contract_v2/test_contract_v2.py gọi 2 hàm dưới).

    apply_setup(app, step)    dựng trạng thái theo bước "setup" của fixture (agent_registered:<HOST>, fs_token:<tok>…)
    check_socket(app, fx)     biến "effect" (mô tả bằng lời) của fixture socket thành phép kiểm cụ thể

Mọi phép kiểm socket đều có "kẻ ngoài cuộc" (máy khác / trình duyệt khác) để chứng minh KHÔNG broadcast (luật A8).
Chỉ dùng trong test — dùng Socket.IO test client của Flask-SocketIO (chế độ threading).
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from flask import Flask
from flask_socketio import SocketIOTestClient

from app.legacy_adapter.adapter import LegacyAdapter
from app.legacy_adapter.state import ACK_MAX_TRIES, ACK_TIMEOUT
from app.legacy_adapter.update_gate import INSTALLER
from app.realtime.hub import DESKTOP_NS, socketio
from app.tenants import service as tsvc
from app.tenants.repo import SettingRepo, UserRepo

FX_HOST, FX_MAC = "A6-301-01", "aa:bb:cc:00:30:01"
OTHER_HOST, OTHER_MAC = "A6-301-02", "aa:bb:cc:00:30:02"


def heartbeat(host: str = FX_HOST, mac: str = FX_MAC, **extra) -> dict:
    return {"hostname": host, "ip": "10.21.30.101", "mac": mac, "cpu": "Intel(R) Core(TM) i5-10500", "ram": "16GB",
            "mainboard": "Dell 0XYZ", "disk": "SSD 256GB", "model": "OptiPlex 7080", "serial": "ABC1234",
            "network": "Intel I219-LM", "cpu_usage": 12.5, "ram_usage": 40.1, "disk_usage": "C:OS:50:100:200",
            "cpu_temp": "N/A", "cpu_fan": "N/A", "cmos_battery": "Bình thường", "client_version": "2.7.5.3", **extra}


def _ad(app: Flask) -> LegacyAdapter:
    return app.extensions["legacy"]


def _clients(app: Flask) -> dict[str, SocketIOTestClient]:
    return app.extensions.setdefault("legacy_contract_clients", {})


_NS: dict[int, str] = {}  # id(test client) → namespace ("/" agent · "/desktop" trình duyệt)


def ns_of(client: SocketIOTestClient) -> str:
    return _NS.get(id(client), "/")


def sid_of(client: SocketIOTestClient) -> str:
    srv: Any = getattr(socketio, "server")  # noqa: B009 — thuộc tính chỉ có sau init_app
    return srv.manager.sid_from_eio_sid(getattr(client, "eio_sid"), ns_of(client))  # noqa: B009


def agent(app: Flask, host: str = FX_HOST, mac: str = FX_MAC) -> SocketIOTestClient:
    """Agent giả: gửi 1 nhịp tim + mở socket + register (như agent 2.7.5.3 lúc khởi động)."""
    _ad(app).state.ingest(heartbeat(host, mac), "127.0.0.1")
    c = socketio.test_client(app)
    c.emit("register", {"hostname": host})
    _clients(app)[host] = c
    return c


def desktop_token(app: Flask) -> str:
    """Token của một Super Admin trong tổ chức gắn agent v2 (tạo nếu chưa có) — trình duyệt giả cần đăng nhập."""
    cache = app.extensions.setdefault("legacy_contract_token", {})
    if "tok" not in cache:
        ad = _ad(app)
        tid = ad.tenant_id
        assert tid is not None, "cần tổ chức gắn agent v2"
        if UserRepo(ad.db, tid).find_one({"username_lc": "contract_admin"}) is None:
            tsvc.create_user(ad.db, tid, "contract_admin", password="Contract@123",
                             policy_ids=[tsvc.super_admin_policy_id(ad.db, tid)])
        r = app.test_client().post("/api/auth/login", json={"tenant_code": ad.s.LEGACY_TENANT_CODE,
                                                             "username": "contract_admin", "password": "Contract@123"})
        cache["tok"] = r.get_json()["token"]
    return cache["tok"]


def browser(app: Flask, token: str | None = None) -> SocketIOTestClient:
    """Desktop giả: nối namespace /desktop bằng token đăng nhập (mặc định Super Admin)."""
    c = socketio.test_client(app, namespace=DESKTOP_NS, auth={"token": token or desktop_token(app)})
    _NS[id(c)] = DESKTOP_NS
    return c


def got(client: SocketIOTestClient, event: str) -> list:
    ns = ns_of(client)
    return [e["args"][0] if e["args"] else None for e in client.get_received(ns) if e["name"] == event]


def write_installer(ad: LegacyAdapter, version: str, body: bytes = b"MZ" + b"\x00" * 30 + b"bo cai thu") -> None:
    d = ad.root / "updates"
    d.mkdir(parents=True, exist_ok=True)
    (d / INSTALLER).write_bytes(body)
    (d / "manifest.json").write_text(json.dumps({"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}),
                                     encoding="utf-8")
    (d / "version.txt").write_text(version, encoding="utf-8")
    ad.gate.invalidate()


# ====================================================================== setup
def apply_setup(app: Flask, step: str) -> None:
    name, _, arg = step.partition(":")
    ad = _ad(app)
    store = ad.store()
    assert store is not None, "test hợp đồng cần tổ chức PHENIKAA (tests/contract_v2/conftest.py)"
    if name == "agent_registered":
        agent(app, arg)
    elif name == "agent_not_registered":
        ad.state.registered.pop(FX_HOST, None)
    elif name == "server_version":
        (ad.root / "updates").mkdir(parents=True, exist_ok=True)
        (ad.root / "updates" / "version.txt").write_text(arg, encoding="utf-8")
    elif name == "rollout_open_for_client":
        SettingRepo(ad.db, store.tid).update_one({"key": "update.all"}, {"$set": {"value": True}}, upsert=True)
        ad.gate.invalidate()
    elif name == "manifest":
        write_installer(ad, arg)
    elif name in ("queue_command", "queue_command_obj"):
        ad.state.ingest(heartbeat(), "127.0.0.1")  # còn nhịp tim nhưng KHÔNG socket → phải vào hàng đợi HTTP
        payload = ({"command": arg} if name == "queue_command"
                   else {"command_obj": {"action": arg, "script": "hostname"}})
        assert ad.dispatch(FX_HOST, "", payload)["channel"] == "http"
    elif name in ("ps_bulk_token", "send_session", "collect_session"):
        kind = {"ps_bulk_token": "ps_bulk", "send_session": "send", "collect_session": "collect"}[name]
        store.create_session(kind, token=arg, meta={"total": 1})
    elif name == "work_batch":
        bid, _, rel = arg.partition(":")
        p = ad.root / "work" / bid / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PK\x03\x04 de thi")
    elif name == "fs_token":
        store.new_fs_token(token=arg)
    elif name == "fs_push":
        tok, _, fname = arg.partition(":")
        store.new_fs_token(token=tok)
        p = store.dir("fs_tmp") / f"{tok}_{fname}"
        p.write_bytes(b"noi dung tep")
        store.fs_set(tok, "push_path", p)
    elif name == "pending_ack":
        agent(app)
        ad.state.track(arg, FX_HOST, FX_MAC, {"command": "logout", "command_id": arg})
    else:
        raise ValueError(f"bước setup lạ: {step}")


# ====================================================================== socket: agent → server
def _in_register(app, fx):
    ad = _ad(app)
    c = socketio.test_client(app)
    c.emit("register", fx["payload"])  # agent gửi tên thường → server tự viết hoa
    assert ad.state.registered.get(FX_HOST) == sid_of(c)
    ad.state.ingest(heartbeat(), "127.0.0.1")
    r = ad.dispatch("a6-301-01", "", {"command": "logout"})
    assert r["channel"] == "socket" and got(c, "execute_command"), r


def _in_disconnect(app, fx):
    ad = _ad(app)
    c = _clients(app)[FX_HOST]
    assert ad.state.is_online(FX_HOST) and ad.state.has_socket(FX_HOST)
    c.disconnect()
    assert not ad.state.has_socket(FX_HOST) and not ad.state.is_online(FX_HOST)
    assert ad.dispatch(FX_HOST, "", {"command": "logout"})["channel"] == "none"


def _in_cmd_ack(app, fx):
    ad = _ad(app)
    cid = fx["payload"]["command_id"]
    assert cid in ad.state.pending
    _clients(app)[FX_HOST].emit("cmd_ack", fx["payload"])
    assert cid not in ad.state.pending


def _in_watch(event_out: str, kind: str):
    def check(app, fx):
        ad = _ad(app)
        watcher, stranger = browser(app), browser(app)
        getattr(socketio, "server").enter_room(sid_of(watcher), ad.room_dev(kind, FX_MAC),  # noqa: B009
                                               namespace=DESKTOP_NS)
        ag = agent(app)
        ag.emit(fx["event"], fx["payload"])
        assert got(watcher, event_out) == [fx["payload"]]
        assert not got(stranger, event_out) and not got(ag, event_out)
    return check


def _in_reply_sid(app, fx):
    br, stranger = browser(app), browser(app)
    ag = agent(app)
    ag.emit(fx["event"], {**fx["payload"], "reply_sid": sid_of(br)})
    out = got(br, fx["event"])
    assert len(out) == 1 and "reply_sid" not in out[0], out
    assert not got(stranger, fx["event"])


def _in_client_update(app, fx):
    ad = _ad(app)
    socketio.test_client(app).emit("client_update", fx["payload"])
    assert ad.state.is_online(FX_HOST)


# ====================================================================== socket: server → agent
def _target_and_stranger(app):
    x = _clients(app).get(FX_HOST) or agent(app)
    y = agent(app, OTHER_HOST, OTHER_MAC)
    x.get_received()
    y.get_received()
    return x, y


def _out_execute_command(app, fx):
    ad = _ad(app)
    t = [time.time()]
    ad.state.clock = lambda: t[0]
    x, y = _target_and_stranger(app)
    r = ad.dispatch(FX_HOST, "", {"command_obj": fx["payload"]["command_obj"]})
    first = got(x, "execute_command")
    assert r["channel"] == "socket" and len(first) == 1 and first[0]["command_id"] == r["command_id"]
    assert first[0]["hostname"] == FX_HOST and not got(y, "execute_command")
    for n in range(2, ACK_MAX_TRIES + 1):  # chưa ACK → gửi lại tới ĐÚNG máy, tối đa 3 lần
        t[0] += ACK_TIMEOUT + 1
        ad.retry_tick()
        again = got(x, "execute_command")
        assert len(again) == 1 and again[0]["command_id"] == r["command_id"], (n, again)
        assert ad.state.pending[r["command_id"]]["tries"] == n
    t[0] += ACK_TIMEOUT + 1
    ad.retry_tick()
    assert not got(x, "execute_command") and r["command_id"] not in ad.state.pending
    assert ad.state.ack_failed[r["command_id"]]["reason"] == "khong_ack"
    assert not got(y, "execute_command")


def _out_send(call: Callable[[LegacyAdapter, str], bool], event: str, expect: Callable[[dict, str], bool]):
    def check(app, fx):
        ad = _ad(app)
        x, y = _target_and_stranger(app)
        br = browser(app)
        assert call(ad, sid_of(br)) is True
        out = got(x, event)
        assert len(out) == 1 and expect(out[0], sid_of(br)), out
        assert not got(y, event) and not got(br, event)
    return check


_CHECKS: dict[str, Callable] = {
    "sock_in_register": _in_register,
    "sock_in_disconnect": _in_disconnect,
    "sock_in_cmd_ack": _in_cmd_ack,
    "sock_in_client_ps_output": _in_watch("ps_output", "ps"),
    "sock_in_client_pty_output": _in_watch("pty_output", "pty"),
    "sock_in_fs_progress": _in_reply_sid,
    "sock_in_fs_response": _in_reply_sid,
    "sock_in_vnc_thumb": _in_reply_sid,
    "sock_in_client_update_legacy": _in_client_update,
    "sock_out_execute_command": _out_execute_command,
    "sock_out_fs_request": _out_send(
        lambda ad, sid: ad.send_fs_request(FX_HOST, {"op": "list", "path": "C:\\", "req_id": "r1"}, sid),
        "fs_request", lambda d, sid: d["reply_sid"] == sid and d["hostname"] == FX_HOST),
    "sock_out_server_ps_input": _out_send(
        lambda ad, sid: ad.send_ps_input(FX_MAC, "dir\r"),
        "server_ps_input", lambda d, sid: d == {"mac": FX_MAC, "data": "dir\r"}),
    "sock_out_server_pty_input": _out_send(
        lambda ad, sid: ad.send_to_host("server_pty_input", {"mac": FX_MAC, "hostname": FX_HOST, "data": "ls\r"},
                                        FX_HOST),
        "server_pty_input", lambda d, sid: d["data"] == "ls\r"),
    "sock_out_server_pty_resize": _out_send(
        lambda ad, sid: ad.send_to_host("server_pty_resize", {"mac": FX_MAC, "hostname": FX_HOST, "cols": 140,
                                                              "rows": 40}, FX_HOST),
        "server_pty_resize", lambda d, sid: (d["cols"], d["rows"]) == (140, 40)),
    "sock_out_vnc_thumb_req": _out_send(
        lambda ad, sid: ad.send_vnc_thumb_req(FX_HOST, sid, False),
        "vnc_thumb_req", lambda d, sid: d == {"hostname": FX_HOST, "reply_sid": sid, "hd": False}),
}


def check_socket(app: Flask, fx: dict) -> None:
    fn = _CHECKS.get(fx["id"])
    if fn is None:
        raise AssertionError(f"chưa có phép kiểm cho fixture {fx['id']}")
    fn(app, fx)
