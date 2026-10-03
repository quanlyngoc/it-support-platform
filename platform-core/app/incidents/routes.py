"""API sự cố — chỉ đọc (Sổ tay 4.6: Dashboard hiện phiếu sự cố + cảnh báo phần cứng). Đăng nhập là xem được, lọc theo
phạm vi phòng của policy (hệ cũ: trang nhật ký sự cố mở cho mọi tài khoản đã đăng nhập)."""
from __future__ import annotations

from typing import Literal

from apiflask import APIBlueprint
from flask import current_app
from pydantic import BaseModel, Field

from app.incidents import service as svc
from app.rbac.perms import login_required
from app.tenants.context import current

bp = APIBlueprint("incidents", __name__, url_prefix="/api", tag="Sự cố")


def _db():
    return current_app.extensions["itm_db"]


class IncidentQuery(BaseModel):
    status: Literal["OPEN", "PENDING", "PROCESSING", "DONE"] | None = Field(
        default=None, description="OPEN = đang chờ + đang xử lý")
    q: str | None = Field(default=None, max_length=64, description="Tìm theo tên máy / tiêu đề / phòng")
    hostname: str | None = Field(default=None, max_length=64, description="Đúng tên máy (không phân biệt hoa thường)")
    room_id: str | None = Field(default=None, max_length=24, description="Sự cố của các máy trong một phòng")
    limit: int = Field(default=200, ge=1, le=1000)


@bp.get("/incidents")
@login_required
@bp.input(IncidentQuery, location="query")
@bp.doc(summary="Danh sách sự cố (mới nhất trước)")
def incidents(query_data: IncidentQuery):
    qd = query_data
    items = svc.list_incidents(_db(), current(), status=qd.status, q=qd.q, hostname=qd.hostname, room_id=qd.room_id,
                               limit=qd.limit)
    return {"items": items, "total": len(items)}


@bp.get("/incidents/summary")
@login_required
@bp.doc(summary="Số phiếu sự cố đang mở + cảnh báo phần cứng đang mở (số tuyệt đối)")
def incidents_summary():
    return svc.summary(_db(), current())
