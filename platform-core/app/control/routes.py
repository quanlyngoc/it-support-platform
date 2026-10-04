"""API điều khiển từ xa (Sổ tay GĐ6). Quyền `device.control` (hệ cũ: "Các chức năng điều khiển") + phạm vi phòng."""
from __future__ import annotations

from typing import Any, Literal

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, Field

from app.control import internet as inet
from app.control import login as lg
from app.control import power as pw
from app.control.targets import LoiDich, resolve
from app.devices import service as devices
from app.rbac.perms import require_perm
from app.realtime.desktop import user_room
from app.tenants.context import current

bp = APIBlueprint("control", __name__, url_prefix="/api", tag="Điều khiển từ xa")


def _db():
    return current_app.extensions["itm_db"]


def _live() -> Any:
    ad = devices._live(current_app.extensions.get("legacy"), current())  # noqa: SLF001 — cùng hệ thống
    if ad is None:
        abort(409, "Tổ chức này chưa có bộ tương thích agent v2 — không gửi lệnh được")
    return ad


def _targets(ad: Any, device_ids: list[str], room_id: str | None, exclude_gv: bool) -> tuple[list[dict], list[dict]]:
    try:
        return resolve(_db(), current(), ad, device_ids=device_ids or None, room_id=room_id, exclude_gv=exclude_gv)
    except LoiDich as e:
        abort(422 if "Cần đúng" in str(e) else 404, str(e))


class TargetsIn(BaseModel):
    device_ids: list[str] = Field(default_factory=list, max_length=2000)
    room_id: str | None = Field(default=None, max_length=24)
    exclude_gv: bool = Field(default=True, description="Cả phòng: chừa máy giảng viên (như hệ cũ)")


class PowerIn(TargetsIn):
    action: Literal["shutdown", "restart", "wake"]


@bp.post("/power")
@require_perm("device.control")
@bp.input(PowerIn)
@bp.doc(summary="Tắt / khởi động lại / bật (Wake-on-LAN qua máy cùng subnet) cho danh sách máy hoặc cả phòng")
def power(json_data: PowerIn):
    ad = _live()
    targets, skipped = _targets(ad, json_data.device_ids, json_data.room_id, json_data.exclude_gv)
    r = pw.wake(ad, targets) if json_data.action == "wake" else pw.shutdown_restart(ad, targets, json_data.action)
    r["skipped"] = skipped + r["skipped"]
    return r


class LoginIn(TargetsIn):
    user: str = Field(min_length=1, max_length=128, description="Tài khoản Windows trên máy trạm (vd. SV, THI)")
    password: str = Field(default="", max_length=256)


@bp.post("/remote-login")
@require_perm("device.control")
@bp.input(LoginIn)
@bp.doc(summary="Đăng nhập Windows từ xa (mã hoá AES-GCM như hệ cũ); kết quả từng máy về sự kiện login_response")
def remote_login(json_data: LoginIn):
    ad = _live()
    targets, skipped = _targets(ad, json_data.device_ids, json_data.room_id, json_data.exclude_gv)
    try:
        r = lg.login(ad, targets, current_app.config["ITM_SETTINGS"].AES_256_KEY_HEX, json_data.user,
                     json_data.password, user_room(current()))
    except lg.ThieuKhoa as e:
        abort(503, str(e))
    r["skipped"] = skipped + r["skipped"]
    return r


@bp.post("/remote-login/logout")
@require_perm("device.control")
@bp.input(TargetsIn)
@bp.doc(summary="Đăng xuất Windows từ xa")
def remote_logout(json_data: TargetsIn):
    ad = _live()
    targets, skipped = _targets(ad, json_data.device_ids, json_data.room_id, json_data.exclude_gv)
    r = lg.logout(ad, targets)
    r["skipped"] = skipped + r["skipped"]
    return r


class InternetIn(TargetsIn):
    action: Literal["disable", "enable", "block_web", "unblock_web"]
    websites: str = Field(default="", max_length=4000, description="Tên miền cách nhau bằng dấu phẩy / xuống dòng")


@bp.post("/internet")
@require_perm("device.control")
@bp.input(InternetIn)
@bp.doc(summary="Ngắt / mở Internet, chặn / bỏ chặn website (lệnh internet_control như hệ cũ)")
def internet_control(json_data: InternetIn):
    ad = _live()
    if json_data.action in ("block_web", "unblock_web") and not json_data.websites.strip():
        abort(422, "Chưa nhập website")
    relay = current_app.config["ITM_SETTINGS"].VNC_RELAY_PUBLIC
    if json_data.action == "disable" and (why := inet.unsafe_reason(relay)):
        abort(409, why)
    targets, skipped = _targets(ad, json_data.device_ids, json_data.room_id, json_data.exclude_gv)
    r = inet.internet(ad, targets, json_data.action, json_data.websites.strip())
    r["skipped"] = skipped + r["skipped"]
    return r
