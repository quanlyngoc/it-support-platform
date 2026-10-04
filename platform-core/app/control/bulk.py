"""PowerShell hàng loạt (Sổ tay 6.4) — thay `/remote_cmd` + `/ps_bulk_status` của hub cũ, CÓ lọc phạm vi phòng.

- Chạy quyền SYSTEM: KHÔNG truyền user/pass (bài học 10.22 hệ cũ — có user/pass thì agent chuyển sang
  `Start-Process -Credential`, ghi HKLM / ProgramData bị "Access is denied").
- Lệnh: `{"command_obj": {"action": "powershell", "script", "user": "", "pass": "", "result_token", "timeout"}}` — agent
  chạy rồi POST `/ps_bulk_result/<token>` → Core lưu MongoDB (`command_results`) + phát `ps_bulk_result` tới room
  `t:<tid>:res:<token>`.
- Bài học 18b ("treo ⏳ mãi"): kết quả có thể về TRƯỚC khi Desktop kịp biết token → Desktop poll `status()` mỗi 3 s;
  máy chưa báo sau `timeout + GRACE` giây thì Core đánh dấu "timeout" ngay khi trả trạng thái (không để trình duyệt
  tự đoán).
- Phiên PHẢI tạo TRƯỚC khi gửi lệnh: agent nhanh (hệ cũ đo 0,2 s) báo kết quả trước khi phiên có thì `/ps_bulk_result`
  bỏ qua → mất kết quả. Gửi xong mới thu hẹp danh sách chờ = máy THỰC SỰ nhận lệnh (máy tắt / mất kênh lệnh báo bỏ qua
  ngay, không treo tới hết giờ).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.legacy_adapter.identity import norm_host

GRACE = 45  # giây chờ thêm sau timeout của agent (hệ cũ: PS_BULK_WAIT_MS = 90 + 45 s)


def start(ad: Any, targets: list[dict], script: str, timeout: int, *, by: str, by_user_id: str,
          limited: bool) -> dict:
    store = ad.store()
    online = [norm_host(d["hostname"]) for d in targets if d.get("is_online")]
    token = store.create_session("ps_bulk", token=uuid.uuid4().hex, meta={  # TRƯỚC khi gửi (xem docstring)
        "total": len(online), "expected": online, "by": by, "by_user_id": by_user_id, "limited": limited,
        "started_at": datetime.now(UTC).isoformat(), "timeout": timeout, "deadline_s": timeout + GRACE,
        "script": script[:300]})
    sent, skipped = [], []
    for d in targets:
        if not d.get("is_online"):
            skipped.append({"hostname": d["hostname"], "reason": "máy đang tắt"})
            continue
        host = norm_host(d["hostname"])
        body = {"command_obj": {"action": "powershell", "script": script, "user": "", "pass": "",
                                "result_token": token, "timeout": timeout}}
        r = ad.dispatch(host, d.get("mac") or "", body)
        if r["channel"] == "none":
            skipped.append({"hostname": d["hostname"], "reason": "mất kênh lệnh"})
        else:
            sent.append({"hostname": host, "channel": r["channel"]})
    if len(sent) != len(online):
        store.update_meta("ps_bulk", token, {"total": len(sent), "expected": [s["hostname"] for s in sent]})
    return {"token": token, "total": len(sent), "sent": sent, "skipped": skipped, "deadline_s": timeout + GRACE}


def status(ad: Any, token: str, now: datetime | None = None) -> dict | None:
    store = ad.store()
    data = store.read(token) if store else None
    if data is None or data["kind"] != "ps_bulk":
        return None
    meta = data["meta"]
    started = datetime.fromisoformat(meta["started_at"])
    elapsed = ((now or datetime.now(UTC)) - started).total_seconds()
    late = elapsed > float(meta.get("deadline_s") or 135)
    got = {r["hostname"]: r for r in data["results"]}
    rows = []
    for host in meta.get("expected", []):
        r = got.get(host)
        if r is None:
            rows.append({"hostname": host, "status": "timeout" if late else "running"})
        else:
            rows.append({k: r.get(k) for k in ("hostname", "status", "exit_code", "stdout", "stderr")})
    finished = sum(1 for r in rows if r["status"] != "running")
    return {"token": data["token"], "started_at": meta["started_at"], "elapsed_s": round(elapsed, 1),
            "deadline_s": meta.get("deadline_s"), "total": len(rows), "finished": finished,
            "complete": finished == len(rows), "by": meta.get("by"), "results": rows,
            "_by_user_id": meta.get("by_user_id"), "_limited": meta.get("limited")}
