"""Chat theo phòng (Sổ tay 8.1) — thay 8 route `/chat/*` của hub cũ.

Mô hình giữ như hệ cũ: mỗi PHÒNG là một hội thoại giữa phía ADMIN (tài khoản không giới hạn phòng / Super Admin) và phía
PHÒNG (tài khoản bị giới hạn phòng — chỉ thấy hội thoại các phòng của mình). Tách kho theo HỆ (`scope`): LAB = hệ
quản lý phòng máy; HSK / PM để dành (chat HSK hiện do ThiHSK tự giữ — tách 09/2026) — cùng một phòng ở hai hệ là hai
hội thoại RIÊNG, không lẫn (truy vấn nào cũng lọc `scope`).

Khác hệ cũ:
- Mốc ĐÃ ĐỌC theo TỪNG NGƯỜI (tenant, user, room, scope) — hệ cũ mọi admin dùng chung một mốc "Admin" (admin này đọc thì
  admin kia mất báo chưa đọc).
- Cảm xúc theo TỪNG NGƯỜI (mỗi người một cảm xúc / tin).
- Ảnh dán lưu kho chung khu `chat` (hệ cũ: thư mục ChatImages), phục vụ qua API có kiểm phạm vi; xoá hội thoại xoá
  kèm ảnh.
- Realtime chỉ tới phía admin + đúng người của phòng (hệ cũ broadcast `chat_event` cho mọi trình duyệt, máy khách tự
  lọc).
"""
from __future__ import annotations

import base64
import io
import time
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.legacy_adapter.identity import is_official_room
from app.realtime.hub import DESKTOP_NS, socketio
from app.storage import TenantFiles
from app.tenants.context import Ctx
from app.tenants.repo import SettingRepo, repo_for

SCOPES = ("LAB", "HSK", "PM")
MAX_TEXT = 1000
MAX_IMG = 6 * 1024 * 1024  # client đã nén JPEG ≤ 1600 px; chặn lạm dụng như hệ cũ
_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


class LoiChat(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


def is_admin(ctx: Ctx) -> bool:
    return ctx.is_super or not ctx.room_ids


def room_admin(tid: Any) -> str:
    return f"t:{tid}:chat:admin"


def room_of_room(tid: Any, rid: Any) -> str:
    return f"t:{tid}:chat:room:{rid}"


def _oid(s: object) -> ObjectId | None:
    try:
        return ObjectId(str(s))
    except Exception:
        return None


def _room(db: Database, ctx: Ctx, room_id: str) -> dict:
    """Phòng của tổ chức mà người này được chat (phía phòng: chỉ phòng của mình)."""
    rid = _oid(room_id)
    if rid is None or (not is_admin(ctx) and rid not in ctx.room_ids):
        raise LoiChat("Không có phòng này hoặc ngoài phạm vi được giao", 404)
    r = repo_for(db, ctx.tenant_id, "rooms").find_one({"_id": rid}, {"name": 1})
    if r is None:
        raise LoiChat("Không có phòng này", 404)
    return r


def _key(kind: str, scope: str, rid: Any) -> str:
    return f"chat_{kind}::{scope}::{rid}"


def _msg_out(m: dict) -> dict:
    return {"id": str(m["_id"]), "sender": m.get("sender") or "", "is_admin": bool(m.get("is_admin")),
            "message": m.get("message") or "", "image": bool(m.get("image")),
            "created_at": m["created_at"].isoformat() if isinstance(m.get("created_at"), datetime) else None}


def me(db: Database, ctx: Ctx) -> dict:
    rooms = []
    if not is_admin(ctx):
        for r in repo_for(db, ctx.tenant_id, "rooms").find({"_id": {"$in": list(ctx.room_ids)}}, {"name": 1}):
            rooms.append({"id": str(r["_id"]), "name": r["name"]})
    return {"side": "admin" if is_admin(ctx) else "room", "name": ctx.username,
            "rooms": sorted(rooms, key=lambda x: x["name"])}


# ====================================================================== danh sách hội thoại + chưa đọc
def conversations(db: Database, ctx: Ctx, scope: str) -> list[dict]:
    """Hội thoại của người này: admin → mọi phòng đã có tin (hoặc được GIỮ sau khi xoá nội dung); phòng → phòng mình.
    Tin cuối + số chưa đọc tính GỘP (vài truy vấn cho cả danh sách, không truy vấn từng phòng — Atlas RTT ≈ 55 ms)."""
    msgs = repo_for(db, ctx.tenant_id, "chat_messages")
    admin = is_admin(ctx)
    if admin:
        rids = {d["_id"] for d in msgs.aggregate([{"$match": {"scope": scope}}, {"$group": {"_id": "$room_id"}}])}
        pre = f"chat_conv::{scope}::"
        for s in SettingRepo(db, ctx.tenant_id).find({"key": {"$regex": "^" + pre}}, {"key": 1}):
            if oid := _oid(s["key"][len(pre):]):
                rids.add(oid)
    else:
        rids = set(ctx.room_ids)
    rids.discard(None)
    if not rids:
        return []
    names = {r["_id"]: r["name"] for r in repo_for(db, ctx.tenant_id, "rooms").find({"_id": {"$in": list(rids)}},
                                                                                       {"name": 1})}
    last = {d["_id"]: d["m"] for d in msgs.aggregate([
        {"$match": {"scope": scope, "room_id": {"$in": list(rids)}}}, {"$sort": {"_id": -1}},
        {"$group": {"_id": "$room_id", "m": {"$first": "$$ROOT"}}}])}
    reads = {d["room_id"]: d.get("last_read_id") for d in repo_for(db, ctx.tenant_id, "chat_reads").find(
        {"user_id": ctx.user_id, "scope": scope, "room_id": {"$in": list(rids)}})}
    unread: dict[Any, int] = {}
    floor = min((v for v in reads.values() if v is not None), default=None)
    q: dict = {"scope": scope, "room_id": {"$in": list(rids)}, "is_admin": not admin}
    if floor is not None and len(reads) == len(rids):
        q["_id"] = {"$gt": floor}
    for d in msgs.find(q, {"room_id": 1}):
        lr = reads.get(d["room_id"])
        if lr is None or d["_id"] > lr:
            unread[d["room_id"]] = unread.get(d["room_id"], 0) + 1
    out = []
    for rid in rids:
        if rid not in names:
            continue
        m = last.get(rid)
        text = (m.get("message") or ("[Hình ảnh]" if m.get("image") else "")) if m else ""
        out.append({"room_id": str(rid), "room_name": names[rid], "official": is_official_room(names[rid]),
                    "unread": unread.get(rid, 0), "last": text[:120], "last_admin": bool(m and m.get("is_admin")),
                    "last_at": m["created_at"].isoformat() if m and isinstance(m.get("created_at"), datetime) else None,
                    "_last_id": m["_id"] if m else ObjectId("0" * 24)})
    # như Zalo: hội thoại CHƯA ĐỌC lên đầu, trong mỗi nhóm theo tin mới nhất; phòng chưa có tin xếp theo tên
    out.sort(key=lambda x: (x["unread"] > 0, x["_last_id"], x["room_name"]), reverse=True)
    for x in out:
        del x["_last_id"]
    return out


def unread_total(db: Database, ctx: Ctx, scope: str) -> int:
    return sum(c["unread"] for c in conversations(db, ctx, scope))


# ====================================================================== tin nhắn
def messages(db: Database, ctx: Ctx, scope: str, room_id: str, since: str | None, active: bool) -> dict:
    room = _room(db, ctx, room_id)
    msgs = repo_for(db, ctx.tenant_id, "chat_messages")
    q: dict = {"scope": scope, "room_id": room["_id"]}
    if s := _oid(since):
        q["_id"] = {"$gt": s}
    rows = list(msgs.find(q).sort("_id", 1).limit(500)) if since else \
        list(reversed(list(msgs.find(q).sort("_id", -1).limit(500))))
    recent = [m["_id"] for m in msgs.find({"scope": scope, "room_id": room["_id"]}, {"_id": 1})
              .sort("_id", -1).limit(200)]
    reacts: dict[str, dict] = {}
    for r in repo_for(db, ctx.tenant_id, "chat_reactions").find({"message_id": {"$in": recent}}):
        d = reacts.setdefault(str(r["message_id"]), {"counts": {}, "mine": ""})
        d["counts"][r["reaction"]] = d["counts"].get(r["reaction"], 0) + 1
        if r["user_id"] == ctx.user_id:
            d["mine"] = r["reaction"]
    if active and recent:
        _mark_read(db, ctx, scope, room["_id"], recent[0])
    tok = SettingRepo(db, ctx.tenant_id).find_one({"key": _key("cleared", scope, room["_id"])})
    return {"room": {"id": str(room["_id"]), "name": room["name"]}, "messages": [_msg_out(m) for m in rows],
            "reactions": reacts, "clear_token": str((tok or {}).get("value") or "0")}


def _mark_read(db: Database, ctx: Ctx, scope: str, rid: ObjectId, last_id: ObjectId) -> None:
    repo_for(db, ctx.tenant_id, "chat_reads").update_one(
        {"user_id": ctx.user_id, "room_id": rid, "scope": scope},
        {"$set": {"last_read_id": last_id, "updated_at": datetime.now(UTC)}}, upsert=True)


def _save_image(kho: TenantFiles, scope: str, rid: ObjectId, mid: ObjectId, data_url: str) -> str:
    try:
        header, b64 = data_url.split(",", 1)
        mime = header.split(";")[0][len("data:"):].strip().lower()
        ext = _EXT.get(mime) if header.startswith("data:image/") else None
        raw = base64.b64decode(b64, validate=True) if ext else b""
    except Exception:
        raise LoiChat("Ảnh không hợp lệ") from None
    if not ext or not raw:
        raise LoiChat("Chỉ nhận ảnh JPEG / PNG / GIF / WEBP")
    if len(raw) > MAX_IMG:
        raise LoiChat("Ảnh quá lớn (tối đa 6 MB)")
    return kho.save("chat", [scope, str(rid), f"{mid}.{ext}"], io.BytesIO(raw), by="chat")["key"]


def _emit(ctx: Ctx, rid: ObjectId, payload: dict) -> None:
    """Chỉ tới phía admin + đúng người của phòng (hệ cũ broadcast cho mọi trình duyệt)."""
    for room in (room_admin(ctx.tenant_id), room_of_room(ctx.tenant_id, rid)):
        socketio.emit("chat_event", payload, to=room, namespace=DESKTOP_NS)


def send(db: Database, ctx: Ctx, kho: TenantFiles, scope: str, room_id: str, message: str,
         image: str | None) -> dict:
    room = _room(db, ctx, room_id)
    text = (message or "").strip()[:MAX_TEXT]
    if not text and not image:
        raise LoiChat("Tin nhắn rỗng")
    mid = ObjectId()
    doc = {"_id": mid, "scope": scope, "room_id": room["_id"], "sender": ctx.username, "sender_id": ctx.user_id,
           "is_admin": is_admin(ctx), "message": text, "created_at": datetime.now(UTC)}
    if image:
        doc["image"] = _save_image(kho, scope, room["_id"], mid, image)
    repo_for(db, ctx.tenant_id, "chat_messages").insert_one(doc)
    _mark_read(db, ctx, scope, room["_id"], mid)  # tin của chính mình không thành "chưa đọc"
    SettingRepo(db, ctx.tenant_id).update_one({"key": _key("conv", scope, room["_id"])}, {"$set": {"value": "1"}},
                                              upsert=True)
    _emit(ctx, room["_id"], {"kind": "message", "scope": scope, "room_id": str(room["_id"]), "room_name": room["name"],
                             "from_admin": doc["is_admin"], "sender": ctx.username, "sender_id": str(ctx.user_id),
                             "preview": (text or "[Hình ảnh]")[:120]})
    return _msg_out(doc)


def react(db: Database, ctx: Ctx, scope: str, msg_id: str, emoji: str) -> dict:
    mid = _oid(msg_id)
    m = repo_for(db, ctx.tenant_id, "chat_messages").find_one({"_id": mid, "scope": scope}) if mid else None
    if m is None:
        raise LoiChat("Không có tin này", 404)  # kể cả tin của HỆ khác — không thả cảm xúc chéo hệ
    if not is_admin(ctx) and m["room_id"] not in ctx.room_ids:
        raise LoiChat("Không có tin này", 404)
    reps = repo_for(db, ctx.tenant_id, "chat_reactions")
    emoji = (emoji or "").strip()[:8]
    cur = reps.find_one({"message_id": mid, "user_id": ctx.user_id})
    reps.delete_many({"message_id": mid, "user_id": ctx.user_id})  # mỗi người một cảm xúc / tin
    mine = ""
    if emoji and not (cur and cur.get("reaction") == emoji):  # bấm lại đúng cảm xúc cũ = bỏ
        reps.insert_one({"message_id": mid, "user_id": ctx.user_id, "reaction": emoji, "created_at": datetime.now(UTC)})
        mine = emoji
    _emit(ctx, m["room_id"], {"kind": "react", "scope": scope, "room_id": str(m["room_id"])})
    return {"mine": mine}


def _xoa_anh(kho: TenantFiles, key: str) -> None:
    """Xoá ảnh; tệp đang bị giữ (ai đó đang tải đúng lúc) → đặt hạn dọn NGAY, worker kho tệp xoá ở lượt sau."""
    try:
        kho.delete(key)
    except OSError:
        kho.meta.update_one({"scope": "storage", "key": key}, {"$set": {"delete_after": datetime.now(UTC)}})


def clear(db: Database, ctx: Ctx, kho: TenantFiles, scope: str, room_id: str | None, keep: bool) -> dict:
    """Admin xoá nội dung một phòng (keep = vẫn giữ hội thoại rỗng trong danh sách) hoặc MỌI phòng của hệ này."""
    if not is_admin(ctx):
        raise LoiChat("Chỉ admin mới xoá được", 403)
    msgs = repo_for(db, ctx.tenant_id, "chat_messages")
    sets = SettingRepo(db, ctx.tenant_id)
    q: dict = {"scope": scope}
    rid = None
    if room_id:
        rid = _room(db, ctx, room_id)["_id"]
        q["room_id"] = rid
    rows = list(msgs.find(q, {"_id": 1, "image": 1, "room_id": 1}))
    for m in rows:
        if m.get("image"):
            _xoa_anh(kho, m["image"])
    ids = [m["_id"] for m in rows]
    msgs.delete_many(q)
    if ids:
        repo_for(db, ctx.tenant_id, "chat_reactions").delete_many({"message_id": {"$in": ids}})
    tok = str(int(time.time()))
    for r in ({rid} if rid else {m["room_id"] for m in rows}):
        sets.update_one({"key": _key("cleared", scope, r)}, {"$set": {"value": tok}}, upsert=True)
        if rid and keep:
            sets.update_one({"key": _key("conv", scope, r)}, {"$set": {"value": "1"}}, upsert=True)
        else:
            sets.delete_one({"key": _key("conv", scope, r)})
        _emit(ctx, r, {"kind": "clear", "scope": scope, "room_id": str(r)})
    if not rid:
        sets.delete_many({"key": {"$regex": f"^chat_conv::{scope}::"}})
    return {"deleted": len(ids), "clear_token": tok}


def image_key(db: Database, ctx: Ctx, msg_id: str) -> str:
    mid = _oid(msg_id)
    m = repo_for(db, ctx.tenant_id, "chat_messages").find_one({"_id": mid}) if mid else None
    if m is None or not m.get("image") or (not is_admin(ctx) and m["room_id"] not in ctx.room_ids):
        raise LoiChat("Không có ảnh này", 404)
    return m["image"]
