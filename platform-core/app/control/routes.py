"""API điều khiển từ xa (Sổ tay GĐ6). Quyền `device.control` (hệ cũ: "Các chức năng điều khiển") + phạm vi phòng."""
from __future__ import annotations

from typing import Any, Literal

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, Field

from app.control import bulk
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


# ====================================================================== 6.4 PowerShell hàng loạt
class BulkIn(TargetsIn):
    script: str = Field(min_length=1, max_length=100_000)
    timeout: int = Field(default=90, ge=5, le=3600, description="Giây agent chờ script (Core chờ thêm 45 s)")


@bp.post("/terminal/bulk")
@require_perm("device.control")
@bp.input(BulkIn)
@bp.doc(summary="Chạy PowerShell quyền SYSTEM trên nhiều máy / cả phòng; kết quả theo token")
def terminal_bulk(json_data: BulkIn):
    ad = _live()
    ctx = current()
    targets, skipped = _targets(ad, json_data.device_ids, json_data.room_id, json_data.exclude_gv)
    r = bulk.start(ad, targets, json_data.script, json_data.timeout, by=ctx.username, by_user_id=str(ctx.user_id),
                   limited=bool(ctx.room_ids) and not ctx.is_super)
    r["skipped"] = skipped + r["skipped"]
    return r


@bp.get("/terminal/bulk/<token>")
@require_perm("device.control")
@bp.doc(summary="Trạng thái từng máy của một lượt chạy hàng loạt (máy quá hạn → timeout)")
def terminal_bulk_status(token: str):
    ctx = current()
    st = bulk.status(_live(), token)
    if st is None:
        abort(404, "Không có lượt chạy này")
    # Người bị giới hạn phòng chỉ xem lượt CỦA MÌNH (tránh lộ kết quả máy phòng khác)
    if ctx.room_ids and not ctx.is_super and st["_by_user_id"] != str(ctx.user_id):
        abort(404, "Không có lượt chạy này")
    return {k: v for k, v in st.items() if not k.startswith("_")}


# ====================================================================== 6.4 Terminal ConPTY một máy
def _device(device_id: str) -> tuple[Any, dict]:
    ad = _live()
    d = devices.get_device(_db(), current(), ad, device_id)
    if d is None:
        abort(404, "Không có máy này")
    if not d.get("mac"):
        abort(409, "Máy chưa có MAC")
    return ad, d


def _send_term(ad: Any, d: dict, obj: dict) -> dict:
    r = ad.dispatch(d["hostname"], d.get("mac") or "", {"command_obj": obj})
    if r["channel"] == "none":
        abort(409, "Máy không còn kênh lệnh (đang tắt hoặc mất kết nối)")
    return {"ok": True, "channel": r["channel"]}


class TermAuthIn(BaseModel):
    user: str = Field(min_length=1, max_length=128, description="Tài khoản Windows (máy cục bộ hoặc DOMAIN\\user)")
    password: str = Field(min_length=1, max_length=256)


@bp.post("/devices/<device_id>/terminal/validate")
@require_perm("device.control")
@bp.input(TermAuthIn)
@bp.doc(summary="Pha 1 terminal: máy xác thực tài khoản Windows (LogonUser) → sự kiện pty_auth_response")
def terminal_validate(device_id: str, json_data: TermAuthIn):
    ad, d = _device(device_id)
    ad.expect_pty(d["mac"], str(current().user_id))
    return _send_term(ad, d, {"action": "pty_validate", "user": json_data.user, "pass": json_data.password})


class TermStartIn(BaseModel):
    cols: int = Field(default=120, ge=20, le=500)
    rows: int = Field(default=30, ge=5, le=200)


@bp.post("/devices/<device_id>/terminal/start")
@require_perm("device.control")
@bp.input(TermStartIn)
@bp.doc(summary="Pha 2 terminal: mở ConPTY đúng cỡ cửa sổ — CHỈ sau khi chính người này vừa xác thực đúng")
def terminal_start(device_id: str, json_data: TermStartIn):
    ad, d = _device(device_id)
    if not ad.take_pty_ok(d["mac"], str(current().user_id)):
        abort(403, "Chưa xác thực tài khoản Windows trên máy này (hoặc đã quá 2 phút) — đăng nhập lại")
    return _send_term(ad, d, {"action": "start_pty", "cols": json_data.cols, "rows": json_data.rows})


@bp.post("/devices/<device_id>/terminal/stop")
@require_perm("device.control")
@bp.doc(summary="Đóng terminal ConPTY của máy")
def terminal_stop(device_id: str):
    ad, d = _device(device_id)
    return _send_term(ad, d, {"action": "stop_pty"})
