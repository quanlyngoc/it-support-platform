"""API cho Desktop / người vận hành điều khiển máy agent v2 (/api/legacy/*).

Chỉ người dùng thuộc ĐÚNG tổ chức gắn với agent v2 mới thấy/điều khiển được (tổ chức khác → 404, đặc tả §4A.36 mục 7).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, Field

from app.legacy_adapter.adapter import LegacyAdapter
from app.legacy_adapter.identity import norm_host
from app.legacy_adapter.update_gate import SETTING_KEYS
from app.rbac.perms import login_required, require_perm
from app.tenants.context import current
from app.tenants.repo import SettingRepo

bp = APIBlueprint("legacy_api", __name__, url_prefix="/api/legacy", tag="Agent v2 (bộ tương thích)")


def _ad() -> LegacyAdapter:
    ad: LegacyAdapter = current_app.extensions["legacy"]
    if ad.tenant_id is None or current().tenant_id != ad.tenant_id:
        abort(404, "Tổ chức này không có máy chạy agent v2")
    return ad


def _unrestricted() -> None:
    """Hai API thô (lệnh theo tên máy, PowerShell hàng loạt) KHÔNG lọc phạm vi phòng → chỉ cho tài khoản không bị giới
    hạn phòng. Người bị giới hạn dùng API GĐ6 có lọc: /api/power, /api/internet, /api/terminal/bulk…"""
    ctx = current()
    if ctx.room_ids and not ctx.is_super:
        abort(403, "Tài khoản giới hạn phòng: dùng các chức năng Điều khiển của Desktop (đã lọc theo phòng được giao)")


@bp.get("/online")
@login_required
@bp.doc(summary="Máy agent v2 đang online + kênh lệnh của từng máy (socket / http / none)")
def online():
    ad = _ad()
    hosts = ad.snapshot()
    return {"total_online": len(hosts), "socket": sum(1 for h in hosts if h["channel"] == "socket"),
            "http_only": sum(1 for h in hosts if h["channel"] == "http"), "hosts": hosts}


class CommandIn(BaseModel):
    hostname: str = Field(min_length=1, max_length=80)
    command: Literal["shutdown", "restart", "logout"] | None = None
    command_obj: dict | None = Field(default=None, description="vd. {\"action\": \"internet_control\", ...}")


@bp.post("/command")
@require_perm("device.control")
@bp.input(CommandIn)
@bp.doc(summary="Gửi 1 lệnh tới 1 máy (không broadcast; máy mất kênh lệnh → 409)")
def command(json_data: CommandIn):
    _unrestricted()
    ad = _ad()
    if (json_data.command is None) == (json_data.command_obj is None):
        abort(422, "Cần đúng một trong hai: command hoặc command_obj")
    if json_data.command_obj is not None and not isinstance(json_data.command_obj.get("action"), str):
        abort(422, "command_obj thiếu action")
    payload = {"command": json_data.command} if json_data.command else {"command_obj": json_data.command_obj}
    r = ad.dispatch(json_data.hostname, "", payload)
    if r["channel"] == "none":
        abort(409, "Máy không còn kênh lệnh (tắt máy hoặc mất kết nối)", extra_data=r)
    return r


class PowerShellIn(BaseModel):
    hostnames: list[str] = Field(min_length=1, max_length=2000)
    script: str = Field(min_length=1, max_length=100_000)
    timeout: int = Field(default=90, ge=5, le=3600)
    user: str = Field(default="", max_length=128, description="Để TRỐNG để chạy quyền SYSTEM (bài học 10.22)")
    password: str = Field(default="", max_length=256)


@bp.post("/powershell")
@require_perm("device.control")
@bp.input(PowerShellIn)
@bp.doc(summary="Chạy PowerShell trên nhiều máy; kết quả về theo token (poll /results/<token> hoặc socket)")
def powershell(json_data: PowerShellIn):
    _unrestricted()
    ad = _ad()
    store = ad.store()
    assert store is not None
    hosts = list(dict.fromkeys(norm_host(h) for h in json_data.hostnames if norm_host(h)))
    token = store.create_session("ps_bulk", meta={"total": len(hosts), "expected": hosts, "by": current().username,
                                                  "started_at": datetime.now(UTC).isoformat()})
    channels = {}
    for host in hosts:
        obj = {"action": "powershell", "script": json_data.script, "user": json_data.user,
               "pass": json_data.password, "result_token": token, "timeout": json_data.timeout}
        channels[host] = ad.dispatch(host, "", {"command_obj": obj})["channel"]
    return {"token": token, "total": len(hosts), "channels": channels,
            "no_channel": [h for h, c in channels.items() if c == "none"]}


@bp.get("/results/<token>")
@require_perm("device.control")
@bp.doc(summary="Kết quả phiên PowerShell / giao bài / thu bài theo token (lưu MongoDB 2 ngày)")
def results(token: str):
    store = _ad().store()
    data = store.read(token) if store else None
    if data is None:
        abort(404, "Không có phiên này")
    return data


class GateIn(BaseModel):
    all: bool = False
    hosts: list[str] = Field(default_factory=list, max_length=2000)
    rollout_rooms: list[str] = Field(default_factory=list, max_length=200)
    rollout_percent: int = Field(default=0, ge=0, le=100)


def _gate_state(ad: LegacyAdapter) -> dict:
    raw = ad.update_settings()
    return {"all": bool(raw.get("update.all")), "hosts": raw.get("update.hosts") or [],
            "rollout_rooms": raw.get("update.rollout_rooms") or [],
            "rollout_percent": int(raw.get("update.rollout_percent") or 0), "manifest": ad.gate.manifest()}


@bp.get("/update_gate")
@require_perm("agent.update")
@bp.doc(summary="Cổng chia đợt cập nhật agent v2 + bộ cài đang phát")
def get_update_gate():
    return _gate_state(_ad())


@bp.put("/update_gate")
@require_perm("agent.update")
@bp.input(GateIn)
@bp.doc(summary="Đặt cổng chia đợt (mặc định TẮT hết). Luôn canary vài máy trước (luật §0.5)")
def put_update_gate(json_data: GateIn):
    ad = _ad()
    assert ad.tenant_id is not None
    repo = SettingRepo(ad.db, ad.tenant_id)
    vals = {"update.all": json_data.all, "update.hosts": [norm_host(h) for h in json_data.hosts if norm_host(h)],
            "update.rollout_rooms": json_data.rollout_rooms, "update.rollout_percent": json_data.rollout_percent}
    assert set(vals) == set(SETTING_KEYS)
    now = datetime.now(UTC)
    for k, v in vals.items():
        repo.update_one({"key": k}, {"$set": {"value": v, "updated_at": now, "updated_by": current().username}},
                        upsert=True)
    ad.gate.invalidate()
    return _gate_state(ad)
