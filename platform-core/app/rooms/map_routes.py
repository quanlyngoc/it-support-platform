"""API sơ đồ phòng (Sổ tay 5.3). Xem: đăng nhập + phòng trong phạm vi policy. Sửa / nhập Excel / xoá: `room_map.edit`.

Mỗi lần lưu: ghi `rooms.map` rồi XUẤT tệp đúng định dạng cũ vào thư mục cho hệ thi (`MAPS_EXPORT_DIR`, mặc định
`<DATA_DIR>/<MÃ TỔ CHỨC>/Maps`) — ThiHSK/ThiPM đọc thư mục đó qua `MONITOR_MAPS_DIR`. Xuất lỗi KHÔNG làm hỏng việc lưu
(Core vẫn là nguồn), nhưng báo về Desktop để người sửa biết hệ thi chưa nhận bản mới (`maps_cli xuat` chạy lại được).
Phòng chưa từng lưu trong Core → đọc tệp của hệ cũ (`LEGACY_MAPS_DIR`, CHỈ ĐỌC).
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from apiflask import APIBlueprint, abort
from bson import ObjectId
from flask import current_app, make_response, request
from pydantic import BaseModel, Field, ValidationError

from app.rbac.perms import login_required, require_perm
from app.realtime.hub import DESKTOP_NS, socketio
from app.rooms import maps
from app.tenants.context import Ctx, current
from app.tenants.repo import repo_for

bp = APIBlueprint("room_maps", __name__, url_prefix="/api", tag="Sơ đồ phòng")

MAX_EXCEL = 5 * 1024 * 1024


def _db():
    return current_app.extensions["itm_db"]


def _s():
    return current_app.config["ITM_SETTINGS"]


def export_dir(settings, tenant_code: str) -> Path:
    if settings.MAPS_EXPORT_DIR:
        return Path(settings.MAPS_EXPORT_DIR)
    return Path(settings.DATA_DIR) / tenant_code / "Maps"


def _room(ctx: Ctx, room_id: str) -> dict:
    try:
        rid = ObjectId(room_id)
    except Exception:
        abort(404, "Không có phòng này")
    if not ctx.is_super and ctx.room_ids and rid not in ctx.room_ids:
        abort(404, "Không có phòng này")
    r = repo_for(_db(), ctx.tenant_id, "rooms").find_one({"_id": rid}, {"name": 1, "map": 1, "map_updated_at": 1,
                                                                        "map_updated_by": 1})
    if r is None:
        abort(404, "Không có phòng này")
    return r


def current_map(r: dict) -> tuple[maps.MapModel | None, str | None]:
    """(sơ đồ, nguồn): Core đã có trường `map` (kể cả đã xoá = None) thì dùng Core; chưa từng có → tệp hệ cũ."""
    if "map" in r:
        return (maps.MapModel.model_validate(r["map"]), "core") if r["map"] else (None, None)
    m = maps.read_legacy(_s().LEGACY_MAPS_DIR, r["name"])
    return (m, "legacy") if m else (None, None)


def _notify(ctx: Ctx, r: dict) -> None:
    socketio.emit("room_map_updated", {"room_id": str(r["_id"]), "by": ctx.username},
                  to=f"t:{ctx.tenant_id}:room:{r['_id']}", namespace=DESKTOP_NS)


@bp.get("/rooms/<room_id>/map")
@login_required
@bp.doc(summary="Sơ đồ phòng (nguồn: core = đã lưu ở Core, legacy = tệp của hệ cũ, null = chưa có)")
def get_map(room_id: str):
    ctx = current()
    r = _room(ctx, room_id)
    m, src = current_map(r)
    up = r.get("map_updated_at")
    return {"room_id": str(r["_id"]), "room_name": r["name"], "map": m.model_dump() if m else None, "source": src,
            "updated_at": up.isoformat() if isinstance(up, datetime) else None, "updated_by": r.get("map_updated_by"),
            "can_edit": ctx.can("room_map.edit")}


@bp.put("/rooms/<room_id>/map")
@require_perm("room_map.edit")
@bp.input(maps.MapModel)
@bp.doc(summary="Lưu sơ đồ + xuất tệp định dạng cũ cho hệ thi")
def put_map(room_id: str, json_data: maps.MapModel):
    ctx = current()
    r = _room(ctx, room_id)
    now = datetime.now(UTC)
    repo_for(_db(), ctx.tenant_id, "rooms").update_by_id(
        r["_id"], {"$set": {"map": json_data.model_dump(), "map_updated_at": now, "map_updated_by": ctx.username}})
    exported, err = None, None
    try:
        exported = maps.export_file(export_dir(_s(), ctx.tenant_code), r["name"], json_data).name
    except (OSError, ValueError) as e:
        err = f"{type(e).__name__}: {e}"
        current_app.logger.warning("Xuất sơ đồ %s cho hệ thi lỗi: %s", r["name"], err)
    _notify(ctx, r)
    return {"ok": True, "source": "core", "updated_at": now.isoformat(), "exported": exported, "export_error": err}


@bp.delete("/rooms/<room_id>/map")
@require_perm("room_map.edit")
@bp.doc(summary="Xoá sơ đồ (không đọc lại tệp hệ cũ nữa) + xoá tệp đã xuất cho hệ thi")
def delete_map(room_id: str):
    ctx = current()
    r = _room(ctx, room_id)
    repo_for(_db(), ctx.tenant_id, "rooms").update_by_id(
        r["_id"], {"$set": {"map": None, "map_updated_at": datetime.now(UTC), "map_updated_by": ctx.username}})
    removed = maps.remove_export(export_dir(_s(), ctx.tenant_code), r["name"])
    _notify(ctx, r)
    return {"ok": True, "export_removed": removed}


@bp.post("/rooms/<room_id>/map/import-excel")
@require_perm("room_map.edit")
@bp.doc(summary="Nhập Excel vào sơ đồ ĐANG SỬA (multipart: file + map JSON tuỳ chọn) — trả sơ đồ mới, CHƯA lưu",
        description="Sheet đầu là lưới số ghế (dòng 1 tiêu đề) → thay toàn bộ máy; hoặc bảng mã thiết bị (cột A "
                    "'ID…') → cập nhật mã màn hình / mã case / mã thiết bị.")
def import_excel(room_id: str):
    ctx = current()
    r = _room(ctx, room_id)
    f = request.files.get("file")
    if f is None:
        abort(422, "Thiếu tệp Excel (trường 'file')")
    data = f.read(MAX_EXCEL + 1)
    if len(data) > MAX_EXCEL:
        abort(413, "Tệp Excel quá 5 MB")
    try:
        base = (maps.MapModel.model_validate_json(request.form["map"]) if request.form.get("map")
                else current_map(r)[0] or maps.MapModel())
        kind, rows = maps.read_excel(data)
    except ValidationError as e:
        abort(422, f"Sơ đồ gửi kèm không hợp lệ: {e.error_count()} lỗi")
    except ValueError as e:
        abort(422, str(e))
    out, n = maps.apply_grid(base, rows) if kind == "grid" else maps.apply_codes(base, rows)
    return {"map": out.model_dump(), "kind": kind, "count": n}


@bp.post("/rooms/<room_id>/map/export-excel")
@login_required
@bp.doc(summary="Xuất Excel (lưới số ghế + mã thiết bị) từ sơ đồ gửi lên, không gửi thì dùng sơ đồ đã lưu")
def export_excel(room_id: str):
    ctx = current()
    r = _room(ctx, room_id)
    body = request.get_json(silent=True)
    try:
        m = maps.MapModel.model_validate(body) if body else current_map(r)[0]
    except ValidationError as e:
        abort(422, f"Sơ đồ gửi kèm không hợp lệ: {e.error_count()} lỗi")
    if m is None:
        abort(404, "Phòng chưa có sơ đồ")
    resp = make_response(maps.to_excel(m, r["name"]))
    resp.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    name = f"So_Do_{maps.safe_name(r['name'])}.xlsx"  # có dấu → header chỉ nhận latin-1 → RFC 5987 filename*
    resp.headers["Content-Disposition"] = f"attachment; filename=So_Do.xlsx; filename*=UTF-8''{quote(name)}"
    return resp


class LiveLayoutIn(BaseModel):
    layout: dict[str, Any] = Field(default_factory=dict, description="{TÊN MÁY: {fx, fy}} — đơn vị ô lưới, 0-based")


@bp.put("/rooms/<room_id>/live-layout")
@require_perm("room_map.edit")
@bp.input(LiveLayoutIn)
@bp.doc(summary="Lưu bố trí lưới View desktop của phòng (mọi người xem cùng một bố trí)")
def put_live_layout(room_id: str, json_data: LiveLayoutIn):
    """Như `/api/live_layout` hệ cũ: chỉ giữ {host: {fx, fy}} hợp lệ (0 ≤ fx, fy < 1000, làm tròn 3 số, ≤ 500 máy)."""
    ctx = current()
    r = _room(ctx, room_id)
    clean: dict[str, dict[str, float]] = {}
    for host, pos in list(json_data.layout.items())[:500]:
        try:
            fx, fy = round(float(pos.get("fx")), 3), round(float(pos.get("fy")), 3)
        except (AttributeError, TypeError, ValueError):
            continue
        if 0 <= fx < 1000 and 0 <= fy < 1000:
            clean[str(host).strip().upper()[:64]] = {"fx": fx, "fy": fy}
    repo_for(_db(), ctx.tenant_id, "rooms").update_by_id(r["_id"], {"$set": {"live_layout": clean}})
    socketio.emit("room_map_updated", {"room_id": str(r["_id"]), "by": ctx.username, "what": "live_layout"},
                  to=f"t:{ctx.tenant_id}:room:{r['_id']}", namespace=DESKTOP_NS)
    return {"ok": True, "count": len(clean)}
