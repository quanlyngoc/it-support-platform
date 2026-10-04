"""Nguồn + Wake-on-LAN (Sổ tay 6.1) — thay `/power_control` của hub cũ.

- Tắt / khởi động lại: lệnh `{"command": "shutdown"|"restart"}` (đúng dạng hub cũ) chỉ tới máy ĐANG BẬT.
  `dispatch` ghi "tắt có chủ ý" NGAY LÚC RA LỆNH (cảnh báo 0.7 + hệ thi không báo động giả khi máy tắt theo lệnh).
- Bật máy: Core KHÔNG bắn gói ma thuật (máy chủ khác VLAN, không tới được máy trạm). Nhờ máy trạm ĐANG BẬT cùng
  subnet /24 bắn hộ bằng `relay_wake_batch {targets: [{mac, ip}]}` — agent chỉ bắn cho máy cùng subnet với chính nó,
  nên mỗi subnet chọn tối đa `HELPERS_PER_SUBNET` máy trung gian (ưu tiên cùng phòng, có socket). Hub cũ "nhờ cả
  trường" (gửi lệnh tới MỌI máy online, máy khác subnet tự bỏ qua) — vô ích mà tốn hàng trăm lệnh; ở đây gom theo
  subnet.
  Subnet không có máy nào đang bật → báo rõ "không có máy trung gian" (bật tay một máy trong phòng đó rồi bấm lại).
"""
from __future__ import annotations

import ipaddress
from typing import Any

from app.legacy_adapter.identity import mac12, norm_host, norm_mac

HELPERS_PER_SUBNET = 2


def _subnet(ip: object) -> str:
    try:
        a = ipaddress.IPv4Address(str(ip or "").strip())
    except ValueError:
        return ""
    if a.is_loopback or a.is_unspecified or a.is_link_local:
        return ""
    return ".".join(str(a).split(".")[:3])


def shutdown_restart(ad: Any, targets: list[dict], action: str) -> dict:
    sent, skipped = [], []
    for d in targets:
        if not d.get("is_online"):
            skipped.append({"hostname": d["hostname"], "reason": "máy đang tắt"})
            continue
        r = ad.dispatch(norm_host(d["hostname"]), d.get("mac") or "", {"command": action})
        if r["channel"] == "none":
            skipped.append({"hostname": d["hostname"], "reason": "mất kênh lệnh"})
        else:
            sent.append({"hostname": d["hostname"], "channel": r["channel"]})
    return {"action": action, "sent": sent, "skipped": skipped}


def wake(ad: Any, targets: list[dict]) -> dict:
    st = ad.state
    skipped: list[dict] = []
    want: list[dict] = []
    for d in targets:
        if d.get("is_online"):
            skipped.append({"hostname": d["hostname"], "reason": "máy đang bật"})
        elif not mac12(d.get("mac")):
            skipped.append({"hostname": d["hostname"], "reason": "chưa biết MAC"})
        else:
            want.append(d)
    # Máy trung gian: đang online + còn kênh lệnh; IP lấy từ NHỊP TIM SỐNG (CSDL có thể cũ)
    peers: dict[str, list[str]] = {}
    for h in st.online_hosts():
        if st.channel(h) == "none":
            continue
        rec = st.hosts.get(h)
        sn = _subnet((rec.hb.get("ip") if rec else "") or (rec.seen_ip if rec else ""))
        if sn:
            peers.setdefault(sn, []).append(h)
    groups: dict[str, list[dict]] = {}
    for d in want:
        groups.setdefault(_subnet(d.get("ip")), []).append(d)
    helpers_out: list[dict] = []
    no_helper: list[str] = []
    for sn, ts in groups.items():
        rooms = {d.get("room_name") for d in ts}
        cands = peers.get(sn, []) if sn else [h for hs in peers.values() for h in hs if ad.room_of(h) in rooms]
        cands = [h for h in cands if h not in {norm_host(d["hostname"]) for d in ts}]
        if not cands:
            no_helper += [d["hostname"] for d in ts]
            continue
        cands.sort(key=lambda h: (ad.room_of(h) not in rooms, st.channel(h) != "socket", h))
        body = {"command_obj": {"action": "relay_wake_batch",
                                "targets": [{"mac": norm_mac(d.get("mac")), "ip": d.get("ip") or ""} for d in ts]}}
        for h in cands[:HELPERS_PER_SUBNET]:
            r = ad.dispatch(h, "", body)
            if r["channel"] != "none":
                helpers_out.append({"helper": h, "subnet": sn or "(theo phòng)", "count": len(ts),
                                    "channel": r["channel"]})
    return {"action": "wake", "targets": len(want), "helpers": helpers_out, "no_helper": no_helper, "skipped": skipped}
