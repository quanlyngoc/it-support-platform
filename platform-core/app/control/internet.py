"""Internet: chặn / mở, chặn / bỏ chặn website (Sổ tay 6.3) — thay `/internet_control` của hub cũ. ⛔ Luật §0.

Lệnh tới agent: `{"command_obj": {"action": "internet_control", "sub_action": ..., "websites": "..."}}` (đúng dạng hub
cũ).
Agent 2.7.5.x khi "disable" (client.py `_action_disable_internet`): WFP khoá hẳn tiến trình trình duyệt + chặn cổng ra
TCP 80/443/8080/8443, UDP 80/443 (netsh làm dự phòng). Agent nói chuyện với máy chủ qua `10.21.24.142:5443` (cả tunnel
VNC `/vncws`) → KHÔNG bị chặn — đã đối chiếu mã agent 04/10/2026. Máy canary chuyển sang Core vẫn đi đúng đường đó.
Chốt §0 ở Core: nếu cấu hình đường agent gọi về (`VNC_RELAY_PUBLIC`) rơi vào cổng agent sẽ chặn thì TỪ CHỐI lệnh
"disable" — ngắt Internet mà cắt luôn đường về máy chủ là máy mất kết nối, phải ra tận nơi.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.legacy_adapter.identity import norm_host

AGENT_BLOCKED_PORTS = frozenset({80, 443, 8080, 8443})  # client.py _action_disable_internet (TCP); UDP 80/443


def unsafe_reason(relay_url: str) -> str | None:
    """Lý do KHÔNG được ngắt Internet (đường agent về máy chủ sẽ bị chặn) — None nếu an toàn."""
    u = urlparse(relay_url or "")
    port = u.port or (443 if u.scheme in ("wss", "https") else 80)
    if port in AGENT_BLOCKED_PORTS:
        return (f"Đường agent gọi về máy chủ ({u.scheme}://{u.hostname}:{port}) nằm trong các cổng agent sẽ chặn khi "
                f"ngắt Internet ({', '.join(map(str, sorted(AGENT_BLOCKED_PORTS)))}) — ngắt là máy mất kết nối (§0)")
    return None


def internet(ad: Any, targets: list[dict], sub_action: str, websites: str) -> dict:
    sent, skipped = [], []
    for d in targets:
        if not d.get("is_online"):
            skipped.append({"hostname": d["hostname"], "reason": "máy đang tắt"})
            continue
        body = {"command_obj": {"action": "internet_control", "sub_action": sub_action, "websites": websites}}
        r = ad.dispatch(norm_host(d["hostname"]), d.get("mac") or "", body)
        if r["channel"] == "none":
            skipped.append({"hostname": d["hostname"], "reason": "mất kênh lệnh"})
        else:
            sent.append({"hostname": d["hostname"], "channel": r["channel"]})
    return {"action": sub_action, "sent": sent, "skipped": skipped}
