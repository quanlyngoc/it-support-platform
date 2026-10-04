"""Xem / điều khiển màn hình (Sổ tay 5.4) — thay `/vnc/open` + `/vnc/close` của hệ cũ; quyền `remote.vnc` + phạm vi
phòng.

Mạng CHẶN chiều máy chủ → máy trạm, nên cả agent lẫn người xem đều GỌI RA relay ghép cặp
(`D:\\RemoteControl\\vnc_relay.py`, dịch vụ `PhenikaaVncRelay`, cổng 6080 sau Caddy `/vncws`); relay ghép theo TOKEN rồi
bơm byte RFB hai chiều. Core chỉ: cấp token ngẫu nhiên, bảo agent mở tunnel (`vnc_start {relay_url, token}`), trả URL
noVNC cho Desktop. Luồng RFB KHÔNG đi qua Core. Relay hiện ghép theo token trùng nhau (chưa kiểm token với máy chủ) —
HOAN_BAO_MAT.

Bài học hệ cũ giữ nguyên (đừng "sửa lại cho gọn"):
- Lệnh PHẢI bọc trong `command_obj` — agent chỉ đọc `data['command_obj']` (bug 11/09: gửi `action` cấp cao nhất →
  agent bỏ qua).
- `path` của noVNC PHẢI tuyệt đối `/vncws?...` (noVNC 1.7 giải đường tương đối theo `/novnc/` → rơi vào file tĩnh).
- Ép `view_only=0` qua URL — noVNC nhớ "View Only" trong localStorage của máy GV, lỡ bấm một lần là mọi phiên chỉ-xem.
- `quality=9&compression=2`: mạng LAN → nét như gốc, không đè CPU máy trạm; `reconnect=true` khớp agent tự nối lại.
"""
from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import quote

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, Field

from app.devices import service as svc
from app.rbac.perms import require_perm
from app.tenants.context import current

bp = APIBlueprint("vnc", __name__, url_prefix="/api", tag="Xem / điều khiển màn hình")


def _ad():
    return current_app.extensions.get("legacy")


def viewer_url(token: str, password: str, base: str = "") -> str:
    path = quote(f"/vncws?role=viewer&token={token}", safe="")
    return (f"{base}/novnc/vnc.html?autoconnect=1&resize=scale&reconnect=true&reconnect_delay=1500"
            f"&view_only=0&quality=9&compression=2&path={path}&password={quote(password, safe='')}")


def _device_host(device_id: str) -> tuple[Any, str]:
    ctx = current()
    d = svc.get_device(current_app.extensions["itm_db"], ctx, _ad(), device_id)  # đã lọc phạm vi phòng + tổ chức
    if d is None:
        abort(404, "Không có máy này")
    ad = svc._live(_ad(), ctx)  # noqa: SLF001 — cùng gói devices
    if ad is None:
        abort(409, "Tổ chức này chưa có bộ tương thích agent v2 — không gửi lệnh được")
    return ad, str(d.get("hostname") or "")


@bp.post("/devices/<device_id>/vnc/open")
@require_perm("remote.vnc")
@bp.doc(summary="Mở phiên xem/điều khiển: cấp token, bảo agent mở tunnel tới relay, trả URL noVNC")
def vnc_open(device_id: str):
    ad, host = _device_host(device_id)
    s = current_app.config["ITM_SETTINGS"]
    token = secrets.token_hex(32)  # 256 bit, như hệ cũ
    r = ad.dispatch(host, "", {"command_obj": {"action": "vnc_start", "relay_url": s.VNC_RELAY_PUBLIC, "token": token}})
    if r["channel"] == "none":
        abort(409, "Máy không còn kênh lệnh (đang tắt hoặc mất kết nối)")
    return {"hostname": r["hostname"], "token": token, "channel": r["channel"],
            "viewer_url": viewer_url(token, s.VNC_PASSWORD, s.VNC_VIEWER_BASE)}


class CloseIn(BaseModel):
    token: str = Field(default="", max_length=128)


@bp.post("/devices/<device_id>/vnc/close")
@require_perm("remote.vnc")
@bp.input(CloseIn)
@bp.doc(summary="Đóng phiên: bảo agent dừng tunnel (không nối lại nữa)")
def vnc_close(device_id: str, json_data: CloseIn):
    ad, host = _device_host(device_id)
    r = ad.dispatch(host, "", {"command_obj": {"action": "vnc_stop"}})
    return {"ok": True, "channel": r["channel"]}
