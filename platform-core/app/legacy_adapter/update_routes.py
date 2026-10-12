"""API Màn Quản trị → Cập nhật Agent (Sổ tay 8.4) — quyền `agent.update`. Luật §0 xem `agent_update.py`.

Đối chiếu hệ cũ: `/api/update_status` → `GET /api/agent-update/status` · `/api/update_now` + `/hubapi/push_update` →
`POST /api/agent-update/push` (+ theo dõi `GET /api/agent-update/push/<token>`) · `/api/all_update` →
`PUT /api/agent-update/all` (BẬT cần xác nhận + bằng chứng canary; TẮT = Dừng khẩn xoá sạch cổng) · mới: kho bản
phát hành `GET /api/agent-update/releases`, `POST /api/agent-update/releases/<bản>/activate`, "Cài lại bản cũ" = push
kèm `version`.
Tài khoản giới hạn phòng chỉ đẩy được máy trong phòng mình; All Update + đổi bản đang phát chỉ tài khoản không giới hạn.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from apiflask import APIBlueprint, abort
from bson import ObjectId
from flask import current_app
from pydantic import BaseModel, Field

from app.devices import service as devsvc
from app.legacy_adapter import agent_update as au
from app.legacy_adapter.adapter import LegacyAdapter
from app.legacy_adapter.identity import norm_host
from app.legacy_adapter.releases import LoiBanPhatHanh, Releases, version_key
from app.legacy_adapter.update_gate import CLOSED, SETTING_KEYS
from app.rbac.perms import require_perm
from app.tenants.context import Ctx, current
from app.tenants.repo import SettingRepo, repo_for

bp = APIBlueprint("agent_update", __name__, url_prefix="/api/agent-update", tag="Cập nhật agent")


def _ad() -> LegacyAdapter:
    ad: LegacyAdapter = current_app.extensions["legacy"]
    if ad.tenant_id is None or current().tenant_id != ad.tenant_id:
        abort(404, "Tổ chức này không có máy chạy agent v2")
    return ad


def _rel(ad: LegacyAdapter) -> Releases:
    return Releases(ad.root / "updates")


def _limited(ctx: Ctx) -> bool:
    return bool(ctx.room_ids) and not ctx.is_super


def _unrestricted() -> None:
    if _limited(current()):
        abort(403, "Chỉ tài khoản không giới hạn phòng mới đổi được cấu hình cập nhật toàn trường")


def _gate(ad: LegacyAdapter) -> dict:
    raw = ad.update_settings()
    return {"all": bool(raw.get("update.all")), "hosts": raw.get("update.hosts") or [],
            "rollout_rooms": raw.get("update.rollout_rooms") or [],
            "rollout_percent": int(raw.get("update.rollout_percent") or 0)}


def _set_gate(ad: LegacyAdapter, vals: dict) -> None:
    assert ad.tenant_id is not None and set(vals) <= set(SETTING_KEYS)
    repo = SettingRepo(ad.db, ad.tenant_id)
    now = datetime.now(UTC)
    for k, v in vals.items():
        repo.update_one({"key": k}, {"$set": {"value": v, "updated_at": now, "updated_by": current().username}},
                        upsert=True)
    ad.gate.invalidate()


def _machines(ad: LegacyAdapter, ctx: Ctx, ids: list[ObjectId] | None = None,
              rooms: list[ObjectId] | None = None) -> list[dict]:
    q: dict[str, Any] = dict(devsvc._scope(ctx))
    if ids is not None:
        q["_id"] = {"$in": ids}
    if rooms is not None:
        if "room_id" in q:
            rooms = [r for r in rooms if r in q["room_id"]["$in"]]
        q["room_id"] = {"$in": rooms}
    out = []
    for d in repo_for(ad.db, ctx.tenant_id, "computers").find(q, {"hostname": 1, "legacy_hostname": 1, "room_name": 1,
                                                                   "room_id": 1, "client_version": 1, "ip": 1,
                                                                   "seen_ip": 1, "last_heartbeat_at": 1}):
        host = devsvc._host(d)
        live = ad.state.hosts.get(host)
        online = bool(live and ad.state.is_online(host))
        ver = str((live.hb.get("client_version") if online and live else None) or d.get("client_version") or "")
        out.append({"device_id": str(d["_id"]), "host": host, "hostname": str(d.get("hostname") or host),
                    "room_name": str(d.get("room_name") or ""), "room_id": str(d.get("room_id") or ""),
                    "version": ver, "online": online, "channel": ad.state.channel(host) if online else "none",
                    "ip": str((live.hb.get("ip") if live else None) or d.get("seen_ip") or d.get("ip") or ""),
                    "last_heartbeat_at": d["last_heartbeat_at"].isoformat()
                    if isinstance(d.get("last_heartbeat_at"), datetime) else None})
    return out


def _invited(ad: LegacyAdapter, m: dict) -> bool:
    """Cổng chia đợt đang mời máy này tự lên bản đang phát?"""
    return ad.gate.decide(m["ip"], m["host"], m["room_name"]) != CLOSED


# ====================================================================== trạng thái
@bp.get("/status")
@require_perm("agent.update")
@bp.doc(summary="Bản đang phát, cổng chia đợt, từng máy: phiên bản / online / tiến độ đợt cài gần nhất")
def status():
    ad = _ad()
    ctx = current()
    cur = _rel(ad).current()
    target = cur["version"] if cur else None
    gate = _gate(ad)
    pushes = au.latest_by_host(repo_for(ad.db, ctx.tenant_id, "command_results"),
                               datetime.now(UTC) - timedelta(days=2))
    hosts_gate = {norm_host(h) for h in gate["hosts"]}
    machines = []
    dem = {"total": 0, "online": 0, "uptodate": 0, "outdated": 0, "offline": 0, "running": 0, "failed": 0}
    for m in _machines(ad, ctx):
        if not m["online"]:
            st = "offline"
        elif not target or not m["version"]:
            st = "unknown"
        elif m["version"] == target:
            st = "uptodate"
        else:
            st = "newer" if version_key(m["version"]) > version_key(target) else "outdated"
        p = pushes.get(m["host"])
        dem["total"] += 1
        dem["online"] += m["online"]
        dem["offline"] += st == "offline"
        dem["uptodate"] += st == "uptodate"
        dem["outdated"] += st in ("outdated", "newer")
        dem["running"] += bool(p and p["state"] in ("running", "waiting"))
        dem["failed"] += bool(p and p["state"] == "error")
        machines.append({**m, "status": st, "push": p, "invited": bool(cur) and _invited(ad, m),
                         "in_gate_hosts": m["host"] in hosts_gate})
    machines.sort(key=lambda x: (x["room_name"], x["hostname"]))
    return {"target": cur, "gate": gate, "summary": dem, "machines": machines, "canary_min": au.CANARY_MIN,
            "many": au.MANY, "push_base": current_app.config["ITM_SETTINGS"].AGENT_UPDATE_BASE,
            "can_global": not _limited(ctx)}


# ====================================================================== đẩy cập nhật / cài lại bản cũ
class PushIn(BaseModel):
    device_ids: list[str] = Field(default_factory=list, max_length=2000)
    room_ids: list[str] = Field(default_factory=list, max_length=200, description="Cả phòng (mọi máy trong phòng)")
    version: str | None = Field(default=None, max_length=20,
                                description="Bỏ trống = bản đang phát; có = cài lại bản đó trong kho (kể cả bản cũ)")
    confirm_many: bool = Field(default=False, description=f"Bắt buộc khi đợt > {au.MANY} máy (luật §0.5)")


def _oids(xs: list[str]) -> list[ObjectId]:
    out = []
    for x in xs:
        try:
            out.append(ObjectId(x))
        except Exception:
            continue
    return out


@bp.post("/push")
@require_perm("agent.update")
@bp.input(PushIn)
@bp.doc(summary="Đẩy lệnh cài AN TOÀN (updater tách rời qua Task Scheduler, kiểm SHA-256) cho máy / phòng chọn")
def push(json_data: PushIn):
    ad = _ad()
    ctx = current()
    d = json_data
    if not d.device_ids and not d.room_ids:
        abort(400, "Chưa chọn máy hoặc phòng")
    rels = _rel(ad)
    cur = rels.current()
    if d.version and (not cur or d.version != cur["version"]):
        r = rels.get(d.version)
        if r is None:
            abort(404, f"Không có bản {d.version} nguyên vẹn trong kho")
        rel = {"version": r["version"], "sha256": r["sha256"], "size": r["size"]}
        query, mode = f"?ver={r['version']}", "reinstall"
    else:
        if not cur:
            abort(409, "Chưa có bộ cài đang phát khớp manifest — nhập + phát hành một bản trước")
        rel, query, mode = cur, "", "reinstall" if d.version else "update"
    ms = []
    if d.device_ids:
        ms += _machines(ad, ctx, ids=_oids(d.device_ids))
    if d.room_ids:
        ms += _machines(ad, ctx, rooms=_oids(d.room_ids))
    seen: set[str] = set()
    ms = [m for m in ms if not (m["host"] in seen or seen.add(m["host"]))]
    if not ms:
        abort(404, "Không có máy nào trong phạm vi được giao")
    if mode == "reinstall" and cur and rel["version"] != cur["version"]:
        moi = [m["hostname"] for m in ms if _invited(ad, m)]
        if moi:
            abort(409, f"Cổng chia đợt đang mời {len(moi)} máy tự lên bản {cur['version']} "
                       f"(vd. {', '.join(moi[:5])}) — hạ xong máy sẽ tự lên lại. Tắt All Update / gỡ máy khỏi "
                       "cổng trước.", extra_data={"hosts": moi})
    busy = au.busy_hosts(repo_for(ad.db, ctx.tenant_id, "command_results"))
    skipped, offline, dang, targets = [], [], [], []
    for m in ms:
        if mode == "update" and m["version"] == rel["version"]:
            skipped.append(m["hostname"])  # đã đúng bản: cài lại là một lần dừng agent vô ích (hệ cũ cũng bỏ qua)
        elif not m["online"]:
            offline.append(m["hostname"])
        elif m["host"] in busy:
            dang.append(m["hostname"])
        else:
            targets.append(m)
    if len(targets) > au.MANY and not d.confirm_many:
        abort(409, f"Đợt này {len(targets)} máy (> {au.MANY}). Luật §0.5: canary vài máy → 1 phòng → nhiều phòng; "
                   "xác nhận lại nếu đã qua canary.", extra_data={"need_confirm": True, "count": len(targets)})
    store = ad.store()
    assert store is not None
    base = current_app.config["ITM_SETTINGS"].AGENT_UPDATE_BASE
    token = store.create_session("ps_bulk", meta={
        "purpose": au.PURPOSE, "expected": [m["host"] for m in targets], "total": len(targets),
        "version": rel["version"], "mode": mode, "by": ctx.username, "started_at": datetime.now(UTC).isoformat()})
    updater = au.updater_script(token, base, rel["version"], rel["sha256"], rel["size"], query)
    script = au.bootstrap_script(updater, base)
    sent, via_http, nochan = [], [], []
    for m in targets:
        ch = ad.dispatch(m["host"], "", {"command_obj": {"action": "powershell", "script": script,
                                                          "result_token": token, "timeout": 300}})["channel"]
        if ch == "none":
            nochan.append(m["hostname"])
        else:
            sent.append(m["hostname"])
            if ch == "http":
                via_http.append(m["hostname"])
    return {"token": token, "version": rel["version"], "mode": mode, "sent": sent, "via_http": via_http,
            "no_channel": nochan, "offline": offline, "busy": dang, "skipped_uptodate": skipped}


@bp.get("/push/<token>")
@require_perm("agent.update")
@bp.doc(summary="Tiến độ một đợt cài theo từng máy")
def push_status(token: str):
    store = _ad().store()
    data = store.read(token) if store else None
    if data is None or (data.get("meta") or {}).get("purpose") != au.PURPOSE:
        abort(404, "Không có đợt cài này")
    stages = {r["hostname"]: au.stage(r) for r in data["results"]}
    return {**data, "stages": {h: stages.get(h, au.stage(None)) for h in data["meta"].get("expected") or []}}


# ====================================================================== All Update + Dừng khẩn
class AllIn(BaseModel):
    on: bool
    confirm: str = Field(default="", max_length=10, description="Bật: gõ đúng chữ BẬT (xác nhận ngay trên giao diện)")


@bp.put("/all")
@require_perm("agent.update")
@bp.input(AllIn)
@bp.doc(summary="All Update BẬT (cần xác nhận + đủ máy canary chạy đúng bản) / TẮT = Dừng khẩn (xoá sạch cổng)")
def all_update(json_data: AllIn):
    ad = _ad()
    _unrestricted()
    if not json_data.on:
        _set_gate(ad, {"update.all": False, "update.hosts": [], "update.rollout_rooms": [],
                       "update.rollout_percent": 0})
        return {"gate": _gate(ad),
                "message": "Đã DỪNG: All Update = Off, cổng chia đợt trống — không máy nào tự cập nhật"}
    if json_data.confirm.strip().upper() not in ("BẬT", "BAT"):
        abort(400, "Gõ đúng chữ BẬT để xác nhận bật All Update")
    cur = _rel(ad).current()
    if not cur:
        abort(409, "Chưa có bộ cài đang phát khớp manifest")
    ok = [m for m in _machines(ad, current()) if m["online"] and m["version"] == cur["version"]]
    if len(ok) < au.CANARY_MIN:
        abort(409, f"Mới {len(ok)} máy online chạy bản {cur['version']} — cần ≥ {au.CANARY_MIN} máy canary cập nhật "
                   "THÀNH CÔNG trước khi bật cho cả trường (luật §0.5–0.6).")
    _set_gate(ad, {"update.all": True})
    return {"gate": _gate(ad), "message": f"Đã BẬT All Update — mọi máy online tự lên bản {cur['version']}. "
                                          "Theo dõi số máy online suốt đợt; tụt bất thường → bấm Dừng khẩn."}


# ====================================================================== kho bản phát hành
@bp.get("/releases")
@require_perm("agent.update")
@bp.doc(summary="Các bản agent trong kho (bản đang phát được đánh dấu)")
def releases():
    return {"items": _rel(_ad()).list(), "current": _rel(_ad()).current()}


@bp.post("/releases/<version>/activate")
@require_perm("agent.update")
@bp.doc(summary="Đưa một bản trong kho thành bản đang phát (không tự đẩy xuống máy nào)")
def activate(version: str):
    ad = _ad()
    _unrestricted()
    if _gate(ad)["all"]:
        abort(409, "All Update đang BẬT — đổi bản đang phát lúc này là đẩy bản chưa canary cho cả trường. Tắt trước.")
    try:
        cur = _rel(ad).activate(version)
    except LoiBanPhatHanh as e:
        abort(400, str(e))
    ad.gate.invalidate()
    return {"current": cur}
