"""API cấu hình kênh cảnh báo sự cố (Sổ tay 8.2) — quyền `system.configure` (hệ cũ: quyền "Cấu hình Hệ thống").

Đối chiếu hệ cũ: `/settings/api/integration_config` → `GET /api/settings/alerts` ·
`/settings/api/integration_save` → `PUT /api/settings/alerts` · `/settings/api/email_test` +
`/settings/api/telegram_test` → `POST /api/settings/alerts/test`.
Khoá Gemini của hệ cũ KHÔNG chuyển (giọng nói đã bỏ — ADR-0014).
"""
from __future__ import annotations

from typing import Literal

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, Field

from app.integrations import alerts
from app.rbac.perms import require_perm
from app.tenants.context import current

bp = APIBlueprint("alerts", __name__, url_prefix="/api/settings", tag="Cấu hình")


def _db():
    return current_app.extensions["itm_db"]


def _master() -> str:
    return current_app.config["ITM_SETTINGS"].MASTER_KEY_B64


class AlertCfg(BaseModel):
    smtp_server: str | None = Field(default=None, max_length=200)
    smtp_port: str | None = Field(default=None, max_length=6)
    sender_email: str | None = Field(default=None, max_length=200)
    receiver_email: str | None = Field(default=None, max_length=2000, description="Nhiều địa chỉ: phẩy / xuống dòng")
    telegram_chat_id: str | None = Field(default=None, max_length=64)
    gmail_app_password: str | None = Field(default=None, max_length=200, description="Để trống = giữ nguyên")
    telegram_bot_token: str | None = Field(default=None, max_length=200, description="Để trống = giữ nguyên")
    clear_gmail_app_password: bool = False
    clear_telegram_bot_token: bool = False


@bp.get("/alerts")
@require_perm("system.configure")
@bp.doc(summary="Cấu hình email + Telegram cảnh báo sự cố (bí mật chỉ trả mặt nạ)")
def get_alerts():
    return alerts.public(_db(), current().tenant_id, _master())


@bp.put("/alerts")
@require_perm("system.configure")
@bp.input(AlertCfg)
@bp.doc(summary="Lưu cấu hình cảnh báo (bí mật để trống = giữ nguyên)")
def put_alerts(json_data: AlertCfg):
    ctx = current()
    try:
        return alerts.save(_db(), ctx.tenant_id, _master(), json_data.model_dump(), ctx.username)
    except alerts.LoiKenh as e:
        abort(400, str(e))


class TestIn(AlertCfg):
    channel: Literal["email", "telegram"]


@bp.post("/alerts/test")
@require_perm("system.configure")
@bp.input(TestIn)
@bp.doc(summary="Gửi thử một kênh (dùng giá trị đang nhập trên form nếu có, không thì giá trị đã lưu)")
def test_alerts(json_data: TestIn):
    d = json_data.model_dump()
    channel = d.pop("channel")
    try:
        return {"ok": True, "message": alerts.test(_db(), current().tenant_id, _master(), channel, d)}
    except alerts.LoiKenh as e:
        return {"ok": False, "message": str(e)}
