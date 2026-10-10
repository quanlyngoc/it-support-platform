"""API chat theo phòng (Sổ tay 8.1). Mọi người đăng nhập đều chat được (như hệ cũ); phía phòng chỉ thấy phòng của mình.

Đối chiếu hệ cũ: `/chat/me` → `GET /api/chat/me` · `/chat/rooms` → `GET /api/chat/conversations` · `/chat/unread` →
`GET /api/chat/unread` · `/chat/poll` → `GET /api/chat/messages` · `/chat/send` → `POST /api/chat/send` ·
`/chat/react` →
`POST /api/chat/react` · `/chat/clear` → `POST /api/chat/clear` · `/chat/image/<tên>` → `GET /api/chat/image/<msg_id>` ·
`/chat/rooms_all` → `GET /api/rooms` (sẵn có). Hệ (`ctx=hsk` của hệ cũ) → tham số `scope` (LAB mặc định).
"""
from __future__ import annotations

from typing import Literal

from apiflask import APIBlueprint, abort
from flask import current_app, send_file
from pydantic import BaseModel, Field

from app.chat import service as svc
from app.rbac.perms import login_required
from app.storage import files_for
from app.tenants.context import current

bp = APIBlueprint("chat", __name__, url_prefix="/api/chat", tag="Chat")
Scope = Literal["LAB", "HSK", "PM"]


def _db():
    return current_app.extensions["itm_db"]


def _run(fn, *a):
    try:
        return fn(*a)
    except svc.LoiChat as e:
        abort(e.code, str(e))


class ScopeQ(BaseModel):
    scope: Scope = "LAB"


class MsgQ(ScopeQ):
    room_id: str = Field(min_length=24, max_length=24)
    since: str | None = Field(default=None, max_length=24, description="Chỉ lấy tin sau id này (poll)")
    active: bool = Field(default=False, description="Đang mở hội thoại → đánh dấu đã đọc")


@bp.get("/me")
@login_required
@bp.input(ScopeQ, location="query")
@bp.doc(summary="Tôi là phía nào (admin / phòng) + các phòng của tôi")
def me(query_data: ScopeQ):
    return svc.me(_db(), current())


@bp.get("/conversations")
@login_required
@bp.input(ScopeQ, location="query")
@bp.doc(summary="Hội thoại của tôi: tin cuối + số chưa đọc (chưa đọc lên đầu)")
def conversations(query_data: ScopeQ):
    return {"items": svc.conversations(_db(), current(), query_data.scope)}


@bp.get("/unread")
@login_required
@bp.input(ScopeQ, location="query")
@bp.doc(summary="Tổng số tin chưa đọc của tôi (huy hiệu)")
def unread(query_data: ScopeQ):
    return {"unread": svc.unread_total(_db(), current(), query_data.scope)}


@bp.get("/messages")
@login_required
@bp.input(MsgQ, location="query")
@bp.doc(summary="Tin của một phòng (500 tin cuối; `since` = chỉ tin mới) + cảm xúc; `active=1` đánh dấu đã đọc")
def messages(query_data: MsgQ):
    q = query_data
    return _run(svc.messages, _db(), current(), q.scope, q.room_id, q.since, q.active)


class SendIn(BaseModel):
    scope: Scope = "LAB"
    room_id: str = Field(min_length=24, max_length=24)
    message: str = Field(default="", max_length=4000)
    image: str | None = Field(default=None, max_length=9_000_000, description="data:image/…;base64 (đã nén ở máy)")


@bp.post("/send")
@login_required
@bp.input(SendIn)
@bp.doc(summary="Gửi tin (chữ và/hoặc ảnh dán)")
def send(json_data: SendIn):
    d = json_data
    return _run(svc.send, _db(), current(), files_for(current_app, current().tenant_id), d.scope, d.room_id, d.message,
                d.image)


class ReactIn(BaseModel):
    scope: Scope = "LAB"
    msg_id: str = Field(min_length=24, max_length=24)
    emoji: str = Field(default="", max_length=16, description="Rỗng hoặc bấm lại cảm xúc cũ = bỏ")


@bp.post("/react")
@login_required
@bp.input(ReactIn)
@bp.doc(summary="Thả / đổi / bỏ cảm xúc (mỗi người một cảm xúc / tin)")
def react(json_data: ReactIn):
    return _run(svc.react, _db(), current(), json_data.scope, json_data.msg_id, json_data.emoji)


class ClearIn(BaseModel):
    scope: Scope = "LAB"
    room_id: str | None = Field(default=None, max_length=24, description="Rỗng = MỌI phòng của hệ này")
    keep: bool = Field(default=False, description="True = xoá nội dung nhưng giữ hội thoại rỗng trong danh sách")


@bp.post("/clear")
@login_required
@bp.input(ClearIn)
@bp.doc(summary="Admin xoá nội dung chat (kèm ảnh)")
def clear(json_data: ClearIn):
    d = json_data
    return _run(svc.clear, _db(), current(), files_for(current_app, current().tenant_id), d.scope, d.room_id, d.keep)


@bp.get("/image/<msg_id>")
@login_required
@bp.doc(summary="Ảnh của một tin (kiểm phạm vi phòng)")
def image(msg_id: str):
    key = _run(svc.image_key, _db(), current(), msg_id)
    kho = files_for(current_app, current().tenant_id)
    p = kho.local_path(key)
    ext = key.rsplit(".", 1)[-1].replace("jpg", "jpeg")
    resp = send_file(p if p is not None else kho.open(key), mimetype=f"image/{ext}", max_age=86400, conditional=True)
    resp.headers["Cache-Control"] = "private, max-age=86400"  # tên theo id tin, không đổi
    return resp
