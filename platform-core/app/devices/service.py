"""Thiết bị (collection `computers`) — Sổ tay 5.1.

Dữ liệu tĩnh (cấu hình, phòng, phòng ép…) đọc từ CSDL; trạng thái SỐNG (online, kênh lệnh, CPU/RAM/Disk) lấy từ RAM của
bộ tương thích agent v2 — chỉ khi người hỏi thuộc đúng tổ chức gắn với agent v2. Máy offline KHÔNG kèm CPU/RAM/Disk
(bài học 10.11 hệ cũ: ghi thẳng ra giao diện sẽ thành "undefined%").

Phạm vi phòng: người dùng có policy giới hạn phòng (`ctx.room_ids`) chỉ thấy/đụng máy của các phòng đó; Super Admin và
policy không giới hạn phòng thấy tất cả.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.legacy_adapter.identity import is_official_room, norm_host, room_from_hostname_raw
from app.rooms.service import PHONG_CHO, ensure_room, sort_key
from app.tenants.context import Ctx
from app.tenants.repo import repo_for

_PROJ = {"tenant_id": 0}
_TEXT = ("hostname", "room_name", "room_override", "move_seat", "mac", "ip", "seen_ip", "model", "serial", "cpu", "ram",
         "mainboard", "disk", "network", "client_version", "cmos_battery", "cpu_temp", "cpu_fan", "source")


def _live(ad: Any, ctx: Ctx) -> Any:
    """Adapter agent v2 nếu người hỏi thuộc đúng tổ chức gắn với nó; không thì None (mọi máy coi như offline)."""
    return ad if ad is not None and ad.tenant_id is not None and ad.tenant_id == ctx.tenant_id else None


def _scope(ctx: Ctx) -> dict:
    if ctx.is_super or not ctx.room_ids:
        return {}
    return {"room_id": {"$in": list(ctx.room_ids)}}


def _host(doc: dict) -> str:
    return str(doc.get("legacy_hostname") or norm_host(doc.get("hostname")))


def public(doc: dict, live: Any) -> dict:
    d: dict = {"id": str(doc["_id"]), "room_id": str(doc["room_id"]) if doc.get("room_id") else None}
    d.update({k: doc.get(k) for k in _TEXT if doc.get(k) not in (None, "")})
    for k in ("last_heartbeat_at", "offline_at", "created_at"):
        if isinstance(doc.get(k), datetime):
            d[k] = doc[k].isoformat()
    host = _host(doc)
    online = bool(live and host and live.state.is_online(host))
    d["is_online"] = online
    d["channel"] = live.state.channel(host) if (live and host) else "none"
    if online:
        hb = live.state.hosts[host].hb
        d.update({k: hb.get(k) for k in ("cpu_usage", "ram_usage", "disk_usage") if k in hb})
    return d


def _oid(s: str) -> ObjectId | None:
    try:
        return ObjectId(s)
    except Exception:
        return None


def list_devices(db: Database, ctx: Ctx, ad: Any, *, room_id: str | None = None, q: str | None = None,
                 online: bool | None = None, limit: int = 2000) -> list[dict]:
    query = dict(_scope(ctx))
    if room_id:
        rid = _oid(room_id)
        if rid is None or ("room_id" in query and rid not in query["room_id"]["$in"]):
            return []
        query["room_id"] = rid
    if q:
        pat = re.escape(q.strip())
        query["$or"] = [{"hostname": {"$regex": pat, "$options": "i"}}, {"mac": {"$regex": pat, "$options": "i"}},
                        {"ip": {"$regex": pat, "$options": "i"}}, {"serial": {"$regex": pat, "$options": "i"}}]
    live = _live(ad, ctx)
    out = [public(d, live) for d in repo_for(db, ctx.tenant_id, "computers").find(query, _PROJ).limit(limit)]
    if online is not None:
        out = [d for d in out if d["is_online"] == online]
    return sorted(out, key=lambda d: str(d.get("hostname") or ""))


def get_device(db: Database, ctx: Ctx, ad: Any, device_id: str) -> dict | None:
    did = _oid(device_id)
    if did is None:
        return None
    doc = repo_for(db, ctx.tenant_id, "computers").find_one({"_id": did, **_scope(ctx)}, _PROJ)
    return public(doc, _live(ad, ctx)) if doc else None


def list_rooms(db: Database, ctx: Ctx, ad: Any) -> list[dict]:
    """Phòng + số máy + số online (online lấy từ RAM — tuyệt đối, không cộng dồn)."""
    comp = repo_for(db, ctx.tenant_id, "computers")
    totals = {r["_id"]: r["n"] for r in comp.aggregate([{"$match": _scope(ctx)},
                                                        {"$group": {"_id": "$room_id", "n": {"$sum": 1}}}])}
    live = _live(ad, ctx)
    online: dict[ObjectId, int] = {}
    if live is not None:
        for d in comp.find(_scope(ctx), {"legacy_hostname": 1, "room_id": 1}):
            if d.get("room_id") and d.get("legacy_hostname") and live.state.is_online(d["legacy_hostname"]):
                online[d["room_id"]] = online.get(d["room_id"], 0) + 1
    rq: dict = {}
    if not ctx.is_super and ctx.room_ids:
        rq = {"_id": {"$in": list(ctx.room_ids)}}
    rooms = [{"id": str(r["_id"]), "name": r["name"], "official": is_official_room(r["name"]),
              "total": totals.get(r["_id"], 0), "online": online.get(r["_id"], 0)}
             for r in repo_for(db, ctx.tenant_id, "rooms").find(rq, {"name": 1})]
    return sorted(rooms, key=lambda r: sort_key(r["name"]))


def get_room(db: Database, ctx: Ctx, ad: Any, room_id: str) -> dict | None:
    rid = _oid(room_id)
    if rid is None or (not ctx.is_super and ctx.room_ids and rid not in ctx.room_ids):
        return None
    r = repo_for(db, ctx.tenant_id, "rooms").find_one({"_id": rid}, {"name": 1, "live_layout": 1})
    if r is None:
        return None
    devs = list_devices(db, ctx, ad, room_id=room_id)
    return {"id": str(rid), "name": r["name"], "official": is_official_room(r["name"]), "total": len(devs),
            "online": sum(1 for d in devs if d["is_online"]), "live_layout": r.get("live_layout") or {},
            "devices": devs}


def move_targets(db: Database, ctx: Ctx) -> list[str]:
    """Phòng đích cho Chuyển phòng — CÓ Phòng chờ (cho phép đẩy ngược máy về Phòng chờ, như /api/move_targets cũ)."""
    names = {r["name"] for r in repo_for(db, ctx.tenant_id, "rooms").find({}, {"name": 1})}
    names.add(PHONG_CHO)
    return sorted(names, key=sort_key)


def machine_events(db: Database, ctx: Ctx, *, q: str | None = None, event: str | None = None,
                   limit: int = 300) -> dict:
    """Nhật ký THAY ĐỔI ĐỊNH DANH MÁY (tráo phần cứng / đổi serial / đổi MAC) + kho lưu trữ — CHỈ ĐỌC (bài học 10.21:
    dữ liệu này là bằng chứng, không có đường sửa/xoá)."""
    query: dict = {}
    if event:
        query["event"] = event
    if q:
        pat = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{f: pat} for f in ("hostname", "other_host", "old_value", "new_value", "note")]
    ev = repo_for(db, ctx.tenant_id, "machine_events").find(query, {"_id": 0, "tenant_id": 0}) \
        .sort("created_at", -1).limit(max(1, min(limit, 2000)))
    arch = repo_for(db, ctx.tenant_id, "computers_archive").find(
        {}, {"_id": 0, "tenant_id": 0, "original_id": 0}).sort("archived_at", -1).limit(200)

    def iso(d: dict) -> dict:
        return {k: (v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, ObjectId) else v)
                for k, v in d.items()}

    return {"events": [iso(d) for d in ev], "archive": [iso(d) for d in arch]}


class LoiChuyen(ValueError):
    pass


def move(db: Database, ctx: Ctx, ad: Any, device_ids: list[str], room_name: str, seat: str = "") -> dict:
    """Ép máy sang phòng khác dù tên máy chưa đổi (máy luân chuyển vật lý). Tên máy tự đã đúng phòng đích → chỉ gỡ ép.
    Số vị trí chỉ có nghĩa cho ĐÚNG 1 máy."""
    room_name = room_name.strip()
    seat = seat.strip()
    if not room_name:
        raise LoiChuyen("Chưa chọn phòng đích")
    if seat and not seat.isdigit():
        raise LoiChuyen("Số vị trí phải là số")
    if len(device_ids) > 1:
        seat = ""
    comp = repo_for(db, ctx.tenant_id, "computers")
    rid = ensure_room(db, ctx.tenant_id, room_name)
    live = _live(ad, ctx)
    w = live.writer() if live is not None else None
    moved, skipped, rooms_cu = [], [], set()
    for s in device_ids:
        did = _oid(s)
        doc = comp.find_one({"_id": did, **_scope(ctx)}) if did else None
        if doc is None:
            skipped.append(s)
            continue
        host = _host(doc)
        rooms_cu.add(str(doc.get("room_name") or ""))
        if room_from_hostname_raw(str(doc.get("hostname") or host)) == room_name:
            comp.update_by_id(doc["_id"], {"$set": {"room_name": room_name, "room_id": rid},
                                           "$unset": {"room_override": "", "move_seat": ""}})
            if w is not None:
                w.clear_override(host)
        else:
            comp.update_by_id(doc["_id"], {"$set": {"room_name": room_name, "room_id": rid, "room_override": room_name,
                                                    "move_seat": seat}})
            if w is not None:
                w.set_override(host, room_name, seat)
        repo_for(db, ctx.tenant_id, "incidents").update_many({"hostname": host}, {"$set": {"room_name": room_name}})
        if live is not None and w is not None:
            w.room_ids[room_name] = rid
            live.state.ui_changed.add(host)
        moved.append(str(doc.get("hostname") or host))
    if live is not None and moved:
        live.notify_rooms(rooms_cu | {room_name})
    return {"moved": moved, "skipped": skipped, "room_id": str(rid), "room_name": room_name}


def delete(db: Database, ctx: Ctx, ad: Any, device_id: str) -> dict | None:
    """Xoá máy khỏi danh sách (thao tác TAY của quản trị). Chép sang `computers_archive` trước — không mất dấu vết;
    lịch sử sự cố giữ nguyên. Máy còn bật thì nhịp tim kế sẽ tạo lại dòng mới ở phòng suy từ tên máy."""
    did = _oid(device_id)
    comp = repo_for(db, ctx.tenant_id, "computers")
    doc = comp.find_one({"_id": did, **_scope(ctx)}) if did else None
    if doc is None:
        return None
    snap = {k: v for k, v in doc.items() if k not in ("_id", "tenant_id")}
    repo_for(db, ctx.tenant_id, "computers_archive").insert_one(
        {**snap, "original_id": doc["_id"], "archived_at": datetime.now(UTC), "reason": f"xoa tay boi {ctx.username}"})
    comp.delete_by_id(doc["_id"])
    host = _host(doc)
    live = _live(ad, ctx)
    if live is not None:
        w = live.writer()
        if w is not None:
            w.forget(host)  # BẮT BUỘC dọn phòng ép: sót là máy bật lại bị ép về phòng cũ (§8.1 hệ cũ)
        live.state.hosts.pop(host, None)  # nhịp tim kế tạo lại máy như máy mới
        live.notify_rooms({str(doc.get("room_name") or "")})
    return {"deleted": str(doc.get("hostname") or host)}
