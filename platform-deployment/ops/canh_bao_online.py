"""Sổ tay bước 0.7 — cảnh báo Telegram khi số máy online của hub cũ tụt bất thường (luật §0.8). CHỈ ĐỌC hệ cũ.

Mỗi phút (Task Scheduler) gọi THẲNG http://127.0.0.1:5009/internal/machines (hub chỉ nhận lời gọi localhost không qua
Caddy) và so với lần trước:
- Rớt bất thường = lần trước online, giờ offline, KHÔNG báo "tắt có chủ ý" (`tat_sach`) trong 15 phút, KHÔNG thuộc
  danh sách canary (máy đã chuyển sang Core thì biến mất khỏi hub là đúng).
- Báo khi ≥ 20 máy online lần trước và rớt ≥ max(5, 10%). Mỗi loại cảnh báo cách nhau tối thiểu 15 phút.
- Không gọi được hub 2 lần liên tiếp → báo NGAY (tình huống tệ nhất: cả trường mất kênh). Gọi lại được → báo đã hồi.
- Mỗi lần chạy ghi 1 dòng baseline: online_<ngày>.csv (giờ, online, còn kênh lệnh socket, tổng máy).

    python canh_bao_online.py          chạy 1 lần (Task Scheduler gọi mỗi phút)
    python canh_bao_online.py --thu    gửi tin thử Telegram
Bí mật (1 dòng mỗi tệp) ở D:\\ITSupportPlatformSecrets: internal_token.txt · telegram_token.txt · telegram_chat.txt
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable

HUB_URL = "http://127.0.0.1:5009/internal/machines"
BI_MAT = pathlib.Path(r"D:\ITSupportPlatformSecrets")
LAM_VIEC = pathlib.Path(r"D:\Backup\baseline")
TAT_CO_CHU_Y = 900   # giây: máy báo tắt có chủ ý trong 15' thì không tính là rớt
NGHI_GIUA = 900      # giây: cùng một loại cảnh báo cách nhau tối thiểu 15'
TOI_THIEU = 20       # dưới 20 máy online (đêm, cuối tuần) thì không xét rớt hàng loạt


def phan_tich(truoc: list[str], machines: list[dict], canary: set[str], now: float) -> tuple[list[str], list[str]]:
    """→ (danh sách online hiện tại, danh sách rớt bất thường so với lần trước)."""
    on = sorted({str(m.get("hostname") or "").upper() for m in machines if m.get("online") and m.get("hostname")})
    tat = {str(m.get("hostname") or "").upper(): float(m.get("tat_sach") or 0) for m in machines}
    on_set = set(on)
    rot = [h for h in truoc if h not in on_set and h not in canary and now - tat.get(h, 0.0) > TAT_CO_CHU_Y]
    return on, rot


def can_bao(so_truoc: int, so_rot: int) -> bool:
    return so_truoc >= TOI_THIEU and so_rot >= max(5, int(so_truoc * 0.10))


def _het_nghi(lan_truoc: float, now: float) -> bool:
    """Được báo lại chưa: chưa từng báo (0) hoặc đã qua NGHI_GIUA giây."""
    return not lan_truoc or now - lan_truoc > NGHI_GIUA


def chay(lam_viec: pathlib.Path, lay: Callable[[], dict], gui: Callable[[str], None], now: float | None = None) -> dict:
    """Một lượt kiểm. `lay` trả JSON /internal/machines, `gui` gửi Telegram (tiêm vào để test)."""
    now = time.time() if now is None else now
    lam_viec.mkdir(parents=True, exist_ok=True)
    f_state = lam_viec / "state.json"
    st = {"online": [], "hub_loi": 0, "bao_rot": 0.0, "bao_hub": 0.0, "hub_da_bao": False}
    try:
        st.update(json.loads(f_state.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    canary: set[str] = set()
    f_canary = lam_viec / "canary_hosts.txt"
    if f_canary.exists():
        canary = {x.strip().upper() for x in f_canary.read_text(encoding="utf-8-sig").splitlines() if x.strip()}

    ket_qua = {"hub": "ok", "online": None, "rot": [], "da_bao": []}
    try:
        data = lay()
        if not data.get("ok"):
            raise RuntimeError("hub trả ok=false (sai token?)")
    except Exception as e:
        st["hub_loi"] = int(st["hub_loi"]) + 1
        ket_qua["hub"] = f"loi: {type(e).__name__}: {e}"
        if st["hub_loi"] >= 2 and _het_nghi(float(st["bao_hub"]), now):
            gui(f"🚨 ITM CẢNH BÁO: KHÔNG gọi được hub cũ (127.0.0.1:5009) {st['hub_loi']} lần liên tiếp — "
                f"kiểm dịch vụ PhenikaaAgentHub NGAY. Lỗi: {type(e).__name__}: {e}")
            st["bao_hub"] = now
            st["hub_da_bao"] = True
            ket_qua["da_bao"].append("hub")
        f_state.write_text(json.dumps(st), encoding="utf-8")
        return ket_qua

    if st.get("hub_da_bao"):  # chỉ báo "đã hồi" cho đợt sự cố ĐÃ được cảnh báo
        gui(f"✅ ITM: hub cũ đã trả lời lại sau {st['hub_loi']} lần lỗi.")
        ket_qua["da_bao"].append("hub_hoi")
    st["hub_loi"], st["hub_da_bao"] = 0, False
    machines = data.get("machines") or []
    on, rot = phan_tich(list(st.get("online") or []), machines, canary, now)
    ket_qua.update(online=len(on), rot=rot)
    nhan_lenh = sum(1 for m in machines if m.get("online") and m.get("nhan_lenh"))
    with (lam_viec / f"online_{dt.datetime.now():%Y%m%d}.csv").open("a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%dT%H:%M:%S},{len(on)},{nhan_lenh},{len(machines)}\n")

    truoc = len(st.get("online") or [])
    if can_bao(truoc, len(rot)) and _het_nghi(float(st["bao_rot"]), now):
        vi_du = ", ".join(rot[:8]) + (" …" if len(rot) > 8 else "")
        gui(f"🚨 ITM CẢNH BÁO: {len(rot)} máy rớt bất thường trong 1 phút (trước {truoc}, nay {len(on)} online). "
            f"Ví dụ: {vi_du}. Nếu vừa sửa Caddy/cập nhật agent: DỪNG và quay lui.")
        st["bao_rot"] = now
        ket_qua["da_bao"].append("rot")
    st["online"] = on
    f_state.write_text(json.dumps(st), encoding="utf-8")
    return ket_qua


# ---------------------------------------------------------------------------------------------- kết nối thật
def _doc(ten: str) -> str:
    return (BI_MAT / ten).read_text(encoding="utf-8-sig").strip()


def lay_hub() -> dict:
    req = urllib.request.Request(HUB_URL, headers={"X-Internal-Token": _doc("internal_token.txt")})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # localhost: không qua proxy hệ thống
    with opener.open(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def gui_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{_doc('telegram_token.txt')}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": _doc("telegram_chat.txt"), "text": text}).encode()
    with urllib.request.urlopen(url, data=body, timeout=20) as r:
        if r.status != 200:
            raise RuntimeError(f"Telegram trả {r.status}")


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        getattr(s, "reconfigure", lambda **_: None)(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--thu", action="store_true", help="gửi tin thử Telegram rồi thoát")
    a = ap.parse_args(argv)
    if a.thu:
        gui_telegram(f"ITM: thử kênh cảnh báo online ({dt.datetime.now():%d/%m/%Y %H:%M}) — nhận được tin này là đạt.")
        print("Đã gửi tin thử Telegram")
        return 0
    try:
        r = chay(LAM_VIEC, lay_hub, gui_telegram)
    except Exception as e:  # vd. Telegram lỗi mạng: ghi lại để người trực thấy, lần chạy sau thử tiếp
        r = {"hub": f"loi chay: {type(e).__name__}: {e}", "online": None, "rot": [], "da_bao": []}
    dong = (f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} hub={r['hub']} online={r['online']} rot={len(r['rot'])} "
            f"da_bao={r['da_bao']}")
    print(dong)
    if r["hub"] != "ok" or r["da_bao"]:  # chạy mỗi phút: chỉ ghi sự kiện, số liệu từng phút đã có trong online_*.csv
        try:
            with (LAM_VIEC / "canh_bao.log").open("a", encoding="utf-8") as f:
                f.write(dong + "\n")
        except OSError:
            pass
    return 0 if r["hub"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
