"""API sự cố (Sổ tay 4.6 + 8.2).

Xem / báo hỏng / bổ sung: đăng nhập là được, trong phạm vi phòng của policy (hệ cũ: mọi tài khoản đã đăng nhập).
Ghi chú IT / xử lý / log máy trạm: quyền `incident.handle` (hệ cũ: nút "Xử lý" chỉ hiện với role admin).
Xuất Excel: quyền `report.export` (hệ cũ: role admin).

Đối chiếu hệ cũ: `/report_issue` → `POST /api/incidents` · `/append_issue` → `POST /api/incidents/<id>/append` ·
`/resolve_issue` → `POST /api/incidents/<id>/resolve` · `/admin` + `/incident_logs` → `GET /api/incidents` ·
`/export_incidents` → `GET /api/incidents/export` · `/api/get_client_logs` → `GET /api/client-logs`.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, Field

from app.incidents import service as svc
from app.integrations import alerts
from app.rbac.perms import login_required, require_perm
from app.reports import excel
from app.tenants.context import Ctx, current

bp = APIBlueprint("incidents", __name__, url_prefix="/api", tag="Sự cố")
TRANG_THAI = {"PENDING": "Chờ xử lý", "PROCESSING": "Đang xử lý", "DONE": "Đã xong"}


def _db():
    return current_app.extensions["itm_db"]


def _master() -> str:
    return current_app.config["ITM_SETTINGS"].MASTER_KEY_B64


def _run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except svc.LoiSuCo as e:
        abort(e.code, str(e))


def _day_start(d: date | None) -> datetime | None:
    """Đầu ngày theo giờ MÁY CHỦ → UTC (dữ liệu lưu UTC)."""
    return datetime.combine(d, time.min).astimezone().astimezone(UTC) if d else None


class IncidentQuery(BaseModel):
    status: Literal["OPEN", "PENDING", "PROCESSING", "DONE"] | None = Field(
        default=None, description="OPEN = đang chờ + đang xử lý")
    q: str | None = Field(default=None, max_length=64,
                          description="Tìm theo tên máy / tiêu đề / phòng / mô tả / người báo / người xử lý")
    hostname: str | None = Field(default=None, max_length=64, description="Đúng tên máy (không phân biệt hoa thường)")
    room_id: str | None = Field(default=None, max_length=24, description="Sự cố của các máy trong một phòng")
    source: Literal["USER", "SYSTEM_WATCHDOG"] | None = None
    date_from: date | None = Field(default=None, description="Từ ngày (giờ máy chủ, gồm cả ngày này)")
    date_to: date | None = Field(default=None, description="Đến ngày (gồm cả ngày này)")
    limit: int = Field(default=200, ge=1, le=5000)


def _filters(qd: IncidentQuery) -> dict:
    return {"status": qd.status, "q": qd.q, "hostname": qd.hostname, "room_id": qd.room_id, "source": qd.source,
            "since": _day_start(qd.date_from),
            "until": _day_start(qd.date_to + timedelta(days=1)) if qd.date_to else None}


@bp.get("/incidents")
@login_required
@bp.input(IncidentQuery, location="query")
@bp.doc(summary="Danh sách sự cố (mới nhất trước)")
def incidents(query_data: IncidentQuery):
    items = svc.list_incidents(_db(), current(), limit=query_data.limit, **_filters(query_data))
    return {"items": items, "total": len(items)}


@bp.get("/incidents/summary")
@login_required
@bp.doc(summary="Số phiếu sự cố đang mở + cảnh báo phần cứng đang mở (số tuyệt đối)")
def incidents_summary():
    return svc.summary(_db(), current())


@bp.get("/incidents/export")
@require_perm("report.export")
@bp.input(IncidentQuery, location="query")
@bp.doc(summary="Xuất Excel báo cáo sửa chữa (cùng bộ lọc với danh sách) — hệ cũ /export_incidents")
def incidents_export(query_data: IncidentQuery):
    docs = svc.find_docs(_db(), current(), limit=50_000, **_filters(query_data))
    rows = []
    for i, d in enumerate(docs, 1):
        nguon = "HỆ THỐNG" if d.get("source") == svc.SYSTEM else (d.get("reporter_name") or "")
        rows.append([i, svc.stamp(d.get("created_at")), d.get("room_name") or "", d.get("hostname") or "", nguon,
                     d.get("description") or d.get("title") or "", d.get("resolver_name") or "",
                     svc.render_notes(d.get("it_notes") or []), TRANG_THAI.get(str(d.get("status")), d.get("status")),
                     svc.stamp(d.get("resolved_at"))])
    data = excel.build([excel.Sheet(
        "Sự cố", "BÁO CÁO SỰ CỐ / SỬA CHỮA",
        ["STT", "Thời gian", "Phòng", "Máy", "Người báo", "Mô tả lỗi", "IT xử lý", "Nội dung xử lý", "Trạng thái",
         "Xong lúc"],
        rows, [6, 15, 16, 13, 16, 60, 14, 60, 12, 15], note=f"{len(rows)} sự cố", wrap_cols={6, 8})])
    return excel.response(data, f"Bao_Cao_Su_Co_{datetime.now():%Y%m%d_%H%M}.xlsx")


@bp.get("/incidents/<incident_id>")
@login_required
@bp.doc(summary="Chi tiết một sự cố (các dòng lỗi + ghi chú IT)")
def incident(incident_id: str):
    return svc.public(_run(svc.get, _db(), current(), incident_id))


class CreateIn(BaseModel):
    device_id: str = Field(min_length=24, max_length=24)
    description: str = Field(min_length=1, max_length=svc.MAX_TEXT)


def _alert(ctx: Ctx):
    db, master = _db(), _master()

    def send(hostname: str, room: str, source: str, description: str) -> None:
        alerts.alert(db, ctx.tenant_id, master, hostname=hostname, room=room, source=source, description=description)

    return send


@bp.post("/incidents")
@login_required
@bp.input(CreateIn)
@bp.doc(summary="Báo hỏng một máy (máy có phiếu đang mở → bổ sung dòng); phiếu mới gửi email + Telegram")
def incident_create(json_data: CreateIn):
    ctx = current()
    doc, appended = _run(svc.create, _db(), ctx, json_data.device_id, json_data.description, alert=_alert(ctx))
    return {"incident": svc.public(doc), "appended": appended}, 200 if appended else 201


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=svc.MAX_TEXT)


@bp.post("/incidents/<incident_id>/append")
@login_required
@bp.input(TextIn)
@bp.doc(summary="Bổ sung một dòng lỗi vào phiếu đang mở (chỉ phiếu do người báo)")
def incident_append(incident_id: str, json_data: TextIn):
    return {"incident": svc.public(_run(svc.append, _db(), current(), incident_id, json_data.text))}


@bp.post("/incidents/<incident_id>/note")
@require_perm("incident.handle")
@bp.input(TextIn)
@bp.doc(summary="Ghi chú IT (nhận xử lý) — phiếu chuyển Đang xử lý, người ghi là người xử lý")
def incident_note(incident_id: str, json_data: TextIn):
    return {"incident": svc.public(_run(svc.note, _db(), current(), incident_id, json_data.text))}


class ResolveIn(BaseModel):
    text: str = Field(min_length=1, max_length=svc.MAX_TEXT, description="Nội dung xử lý (bắt buộc)")
    lines: list[int] = Field(default_factory=list, max_length=500,
                             description="Số thứ tự các dòng đã xử lý; rỗng = xong cả phiếu")


@bp.post("/incidents/<incident_id>/resolve")
@require_perm("incident.handle")
@bp.input(ResolveIn)
@bp.doc(summary="Xử lý: đánh dấu các dòng đã xong (hoặc cả phiếu) + ghi nội dung xử lý")
def incident_resolve(incident_id: str, json_data: ResolveIn):
    return {"incident": svc.public(_run(svc.resolve, _db(), current(), incident_id, json_data.text,
                                        json_data.lines))}


class LogQuery(BaseModel):
    hostname: str | None = Field(default=None, max_length=64)
    q: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=100, ge=1, le=1000)


@bp.get("/client-logs")
@require_perm("incident.handle")
@bp.input(LogQuery, location="query")
@bp.doc(summary="Log lỗi agent máy trạm gửi về (/client_log) — mới nhất trước")
def client_logs(query_data: LogQuery):
    items = svc.client_logs(_db(), current(), hostname=query_data.hostname, q=query_data.q, limit=query_data.limit)
    return {"items": items, "total": len(items)}
