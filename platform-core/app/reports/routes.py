"""API báo cáo (Sổ tay 8.2). Xem: đăng nhập là được, lọc theo phạm vi phòng (hệ cũ: mọi tài khoản đã đăng nhập).
Xuất Excel: quyền `report.export` (hệ cũ: role admin).

Đối chiếu hệ cũ: `/admin/stats` → `GET /api/reports/usage` · `/admin/export_stats_excel` →
`GET /api/reports/usage/export` · `/reports` → `GET /api/reports/usage/series` · `/report/<ngày>` →
`GET /api/reports/usage/day` · `/history` → `GET /api/reports/hardware-history` · `/export_excel` (danh sách máy) →
`GET /api/reports/config-export` (sheet "Chi tiết máy", có sẵn từ 5.5).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from apiflask import APIBlueprint, abort
from flask import current_app
from pydantic import BaseModel, Field

from app.rbac.perms import login_required, require_perm
from app.reports import excel
from app.reports import service as svc
from app.tenants.context import current

bp = APIBlueprint("reports", __name__, url_prefix="/api/reports", tag="Báo cáo")


def _db():
    return current_app.extensions["itm_db"]


class UsageQ(BaseModel):
    year: int = Field(default_factory=lambda: datetime.now().year, ge=2020, le=2100)
    month: int | None = Field(default=None, ge=1, le=12, description="Bỏ trống = cả năm")
    room_id: str | None = Field(default=None, max_length=24)


@bp.get("/usage")
@login_required
@bp.input(UsageQ, location="query")
@bp.doc(summary="Thống kê thời gian sử dụng theo phòng / máy trong năm (hoặc tháng)")
def usage(query_data: UsageQ):
    return svc.usage(_db(), current(), query_data.year, query_data.month, query_data.room_id)


def _gio(minutes: int) -> float:
    return round(minutes / 60, 1)


@bp.get("/usage/export")
@require_perm("report.export")
@bp.input(UsageQ, location="query")
@bp.doc(summary="Xuất Excel thống kê sử dụng (theo máy · theo phòng · theo tháng)")
def usage_export(query_data: UsageQ):
    qd = query_data
    ctx = current()
    u = svc.usage(_db(), ctx, qd.year, qd.month, qd.room_id)
    ky = f"{qd.month:02d}/{qd.year}" if qd.month else str(qd.year)
    may, phong, stt = [], [], 0
    for r in u["rooms"]:
        for m in r["machines"]:
            stt += 1
            may.append([stt, r["room_name"], m["hostname"] + (" (đã xoá)" if m.get("deleted") else ""), m["minutes"],
                        _gio(m["minutes"]), m["days"]])
        n = len(r["machines"])
        phong.append([r["room_name"], n, r["used"], _gio(r["minutes"]), _gio(r["minutes"] // n) if n else 0])
    sheets = [
        excel.Sheet("Theo máy", f"THỐNG KÊ SỬ DỤNG THEO MÁY — {ky}",
                    ["STT", "Phòng", "Tên máy", "Tổng phút", "Tổng giờ", "Số ngày có dùng"], may,
                    [6, 18, 16, 12, 11, 15], note=f"{u['machines']} máy",
                    total=["", "TỔNG", "", u["total_minutes"], _gio(u["total_minutes"]), ""]),
        excel.Sheet("Theo phòng", f"THỐNG KÊ SỬ DỤNG THEO PHÒNG — {ky}",
                    ["Phòng", "Số máy", "Số máy có dùng", "Tổng giờ", "TB giờ / máy"], phong, [20, 10, 15, 12, 14],
                    total=["TOÀN BỘ", u["machines"], u["used"], _gio(u["total_minutes"]), ""]),
    ]
    if not qd.month:
        s = svc.series(_db(), ctx, "month", date(qd.year, 1, 1), date(qd.year, 12, 31), qd.room_id)
        sheets.append(excel.Sheet("Theo tháng", f"THỐNG KÊ SỬ DỤNG THEO THÁNG — {qd.year}",
                                  ["Tháng", "Tổng giờ", "Số máy có dùng"],
                                  [[p["period"], _gio(p["minutes"]), p["machines"]] for p in s], [12, 12, 16]))
    data = excel.build(sheets)
    return excel.response(data, f"Thong_Ke_Su_Dung_{qd.year}{f'_{qd.month:02d}' if qd.month else ''}.xlsx")


class SeriesQ(BaseModel):
    group: Literal["day", "month"] = "day"
    date_from: date | None = Field(default=None, description="Mặc định: 30 ngày / 12 tháng gần nhất")
    date_to: date | None = None
    room_id: str | None = Field(default=None, max_length=24)


@bp.get("/usage/series")
@login_required
@bp.input(SeriesQ, location="query")
@bp.doc(summary="Tổng giờ sử dụng + số máy có dùng theo NGÀY hoặc THÁNG (vẽ biểu đồ, danh sách báo cáo ngày)")
def usage_series(query_data: SeriesQ):
    qd = query_data
    lo, hi = svc.default_range(qd.group, date.today())
    lo, hi = qd.date_from or lo, qd.date_to or hi
    if hi < lo:
        abort(400, "Khoảng ngày không hợp lệ")
    if (hi - lo).days > 3700:
        abort(400, "Khoảng ngày quá dài (tối đa ~10 năm)")
    return {"group": qd.group, "date_from": lo.isoformat(), "date_to": hi.isoformat(),
            "items": svc.series(_db(), current(), qd.group, lo, hi, qd.room_id)}


class DayQ(BaseModel):
    day: date = Field(description="Ngày cần xem (YYYY-MM-DD)")
    room_id: str | None = Field(default=None, max_length=24)


@bp.get("/usage/day")
@login_required
@bp.input(DayQ, location="query")
@bp.doc(summary="Báo cáo một ngày: các máy có dùng + số phút + RAM + lần cuối RAM thay đổi")
def usage_day(query_data: DayQ):
    items = svc.day(_db(), current(), query_data.day, query_data.room_id)
    return {"date": query_data.day.isoformat(), "items": items, "total": len(items),
            "minutes": sum(i["minutes"] for i in items)}


class HwQ(BaseModel):
    q: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=500, ge=1, le=5000)


@bp.get("/hardware-history")
@login_required
@bp.input(HwQ, location="query")
@bp.doc(summary="Lịch sử RAM / ổ cứng thay đổi (cũ → mới) kèm MAC — hệ cũ /history")
def hardware_history(query_data: HwQ):
    items = svc.hardware_history(_db(), current(), q=query_data.q, limit=query_data.limit)
    return {"items": items, "total": len(items)}
