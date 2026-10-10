"""Báo cáo (Sổ tay 8.2) — thay 4 trang báo cáo của hệ cũ (CHỈ ĐỌC: D:\\NetworkInventory\\app.py):
- `/admin/stats` + `/admin/export_stats_excel` → `usage()`: tổng phút sử dụng theo máy / phòng trong năm (hoặc tháng).
- `/reports` → `series()`: theo NGÀY / THÁNG — tổng giờ + số máy có dùng (hệ cũ chỉ liệt kê 30 ngày có `last_update`).
- `/report/<ngày>` → `day()`: các máy có dùng trong ngày + RAM + lần cuối RAM đổi.
- `/history` → `hardware_history()`: lịch sử RAM / ổ cứng thay đổi (sự cố SYSTEM_WATCHDOG) kèm MAC.

Nguồn `usage_stats` do bộ ghi nền cộng +1 phút/máy online mỗi 60 s (`{device_id, date "YYYY-MM-DD", online_minutes}`).
Mọi aggregation đi qua TenantRepo.aggregate → stage đầu luôn là `$match: {tenant_id}` (Sổ tay 8.2).
Phạm vi phòng: người bị giới hạn phòng chỉ thấy máy đang thuộc các phòng của mình.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.devices import service as devsvc
from app.incidents.service import SYSTEM
from app.rooms.service import sort_key
from app.tenants.context import Ctx
from app.tenants.repo import repo_for


def _nat(s: object) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s or ""))]


def _room_sort(name: str) -> tuple:
    k = sort_key(name)
    return (k[0], _nat(k[1]))


def _period(year: int, month: int | None) -> tuple[str, str]:
    """Khoảng [từ, đến) dạng chuỗi ngày để so với `usage_stats.date`."""
    if month:
        lo = date(year, month, 1)
        hi = date(year + (month == 12), month % 12 + 1, 1)
    else:
        lo, hi = date(year, 1, 1), date(year + 1, 1, 1)
    return lo.isoformat(), hi.isoformat()


def _devices(db: Database, ctx: Ctx, room_id: str | None) -> dict[ObjectId, dict] | None:
    """Máy trong phạm vi (+ lọc phòng). None = không lọc gì (người không giới hạn phòng, không chọn phòng)."""
    q = dict(devsvc._scope(ctx))
    if room_id:
        try:
            rid = ObjectId(room_id)
        except Exception:
            return {}
        if "room_id" in q and rid not in q["room_id"]["$in"]:
            return {}
        q["room_id"] = rid
    elif not q:
        return None
    return {d["_id"]: d for d in repo_for(db, ctx.tenant_id, "computers").find(
        q, {"hostname": 1, "legacy_hostname": 1, "room_name": 1, "ram": 1, "mac": 1})}


def _match(base: dict, devs: dict | None) -> dict:
    return {**base, "device_id": {"$in": list(devs)}} if devs is not None else base


# ====================================================================== thống kê sử dụng (năm / tháng)
def usage(db: Database, ctx: Ctx, year: int, month: int | None = None, room_id: str | None = None) -> dict:
    lo, hi = _period(year, month)
    devs = _devices(db, ctx, room_id)
    rows = {r["_id"]: r for r in repo_for(db, ctx.tenant_id, "usage_stats").aggregate([
        {"$match": _match({"date": {"$gte": lo, "$lt": hi}}, devs)},
        {"$sort": {"date": 1}},
        {"$group": {"_id": "$device_id", "minutes": {"$sum": "$online_minutes"}, "days": {"$sum": 1},
                    "hostname": {"$last": "$hostname"}, "room_name": {"$last": "$room_name"}}}])}
    if devs is None:  # gồm cả máy CHƯA dùng phút nào (hệ cũ LEFT JOIN computers)
        devs = {d["_id"]: d for d in repo_for(db, ctx.tenant_id, "computers").find(
            {}, {"hostname": 1, "legacy_hostname": 1, "room_name": 1})}
    machines: list[dict] = []
    for did, d in devs.items():
        r = rows.pop(did, None) or {}
        machines.append({"device_id": str(did), "hostname": str(d.get("hostname") or devsvc._host(d)),
                         "room_name": str(d.get("room_name") or "Chưa phân loại"),
                         "minutes": int(r.get("minutes") or 0), "days": int(r.get("days") or 0)})
    if not (ctx.room_ids and not ctx.is_super) and not room_id:
        for did, r in rows.items():  # máy đã bị xoá tay nhưng còn số liệu trong kỳ — giữ để tổng không hụt
            machines.append({"device_id": str(did), "hostname": str(r.get("hostname") or "?"),
                             "room_name": str(r.get("room_name") or "Chưa phân loại"), "minutes": int(r["minutes"]),
                             "days": int(r["days"]), "deleted": True})
    by_room: dict[str, list[dict]] = {}
    for m in machines:
        by_room.setdefault(m["room_name"], []).append(m)
    rooms = []
    for name in sorted(by_room, key=_room_sort):
        ms = sorted(by_room[name], key=lambda m: _nat(m["hostname"]))
        rooms.append({"room_name": name, "minutes": sum(m["minutes"] for m in ms),
                      "used": sum(1 for m in ms if m["minutes"]), "machines": ms})
    return {"year": year, "month": month, "total_minutes": sum(r["minutes"] for r in rooms),
            "machines": len(machines), "used": sum(r["used"] for r in rooms), "rooms": rooms}


# ====================================================================== chuỗi theo ngày / tháng
def series(db: Database, ctx: Ctx, group: str, date_from: date, date_to: date,
           room_id: str | None = None) -> list[dict]:
    devs = _devices(db, ctx, room_id)
    key: Any = "$date" if group == "day" else {"$substr": ["$date", 0, 7]}
    out = []
    for r in repo_for(db, ctx.tenant_id, "usage_stats").aggregate([
            {"$match": _match({"date": {"$gte": date_from.isoformat(), "$lte": date_to.isoformat()}}, devs)},
            {"$group": {"_id": key, "minutes": {"$sum": "$online_minutes"}, "devs": {"$addToSet": "$device_id"}}},
            {"$project": {"minutes": 1, "machines": {"$size": "$devs"}}},
            {"$sort": {"_id": 1}}]):
        out.append({"period": r["_id"], "minutes": int(r["minutes"]), "machines": int(r["machines"])})
    return out


# ====================================================================== báo cáo một ngày
def day(db: Database, ctx: Ctx, d: date, room_id: str | None = None) -> list[dict]:
    devs = _devices(db, ctx, room_id)
    usage_rows = list(repo_for(db, ctx.tenant_id, "usage_stats").find(_match({"date": d.isoformat()}, devs),
                                                                      {"device_id": 1, "online_minutes": 1,
                                                                       "hostname": 1, "room_name": 1}))
    ids = [u["device_id"] for u in usage_rows]
    comp = {c["_id"]: c for c in repo_for(db, ctx.tenant_id, "computers").find(
        {"_id": {"$in": ids}}, {"hostname": 1, "legacy_hostname": 1, "room_name": 1, "ram": 1})}
    hosts = [devsvc._host(c) for c in comp.values()]
    ram_doi: dict[str, Any] = {}
    for r in repo_for(db, ctx.tenant_id, "incidents").aggregate([
            {"$match": {"source": SYSTEM, "category": "hardware_ram", "hostname": {"$in": hosts}}},
            {"$group": {"_id": "$hostname", "at": {"$max": "$created_at"}}}]):
        ram_doi[r["_id"]] = r["at"]
    out = []
    for u in usage_rows:
        c = comp.get(u["device_id"]) or {}
        host = devsvc._host(c) if c else str(u.get("hostname") or "")
        at = ram_doi.get(host)
        out.append({"device_id": str(u["device_id"]), "hostname": str(c.get("hostname") or u.get("hostname") or "?"),
                    "room_name": str(c.get("room_name") or u.get("room_name") or ""),
                    "minutes": int(u.get("online_minutes") or 0), "ram": c.get("ram") or "",
                    "ram_changed_at": at.isoformat() if at else None})
    out.sort(key=lambda m: (_room_sort(m["room_name"]), _nat(m["hostname"])))
    return out


# ====================================================================== lịch sử RAM / ổ cứng
_LOAI = {"hardware_ram": "RAM", "hardware_disk": "Ổ cứng"}


def hardware_history(db: Database, ctx: Ctx, *, q: str | None = None, limit: int = 500) -> list[dict]:
    from app.incidents.service import find_docs

    docs = find_docs(db, ctx, source=SYSTEM, q=q, limit=limit * 2)
    docs = [d for d in docs if d.get("category") in _LOAI][:limit]
    hosts = {str(d.get("hostname") or "") for d in docs}
    macs = {devsvc._host(c): c.get("mac") or "" for c in repo_for(db, ctx.tenant_id, "computers").find(
        {"legacy_hostname": {"$in": list(hosts)}}, {"legacy_hostname": 1, "hostname": 1, "mac": 1})}
    out = []
    for d in docs:
        desc = str(d.get("description") or "")
        kieu, _, rest = desc.partition(": ")
        cu, _, moi = rest.partition(" -> ")
        out.append({"id": str(d["_id"]), "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
                    "hostname": d.get("hostname") or "", "room_name": d.get("room_name") or "",
                    "mac": macs.get(str(d.get("hostname") or ""), ""), "part": _LOAI[d["category"]],
                    "event_type": kieu or str(d.get("title") or ""), "old_value": cu, "new_value": moi,
                    "status": d.get("status") or ""})
    return out


def default_range(group: str, today: date) -> tuple[date, date]:
    """Mặc định: 30 ngày gần nhất (theo ngày) hoặc 12 tháng gần nhất (theo tháng)."""
    if group == "day":
        return today - timedelta(days=29), today
    y, m = today.year, today.month - 11
    if m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1), today
