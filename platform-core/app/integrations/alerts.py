"""Kênh cảnh báo sự cố: Telegram + email (Sổ tay 8.2) — thay `send_alert_email_thread` + 4 route
`/settings/api/integration_*|email_test|telegram_test` của hệ cũ (CHỈ ĐỌC: D:\\NetworkInventory\\utils.py, app.py).

- Cấu hình THEO TỔ CHỨC trong `settings` (key `alert_channels`). Bí mật (mật khẩu ứng dụng Gmail, token bot Telegram)
  mã hoá AES-256-GCM bằng MASTER_KEY_B64 (app.security.crypto) — API chỉ trả MẶT NẠ (`***` đúng độ dài) như hệ cũ.
  HOAN_BAO_MAT: khoá chủ đang là khoá mặc định của giai đoạn dựng thử (config/settings.py).
- Gửi trong TÁC VỤ NỀN (greenlet dưới gevent) — request báo hỏng / bộ ghi nền KHÔNG chờ SMTP 5–15 s. Telegram trước
  (nhanh, rung điện thoại), email sau — đúng thứ tự hệ cũ. Kênh nào để trống thì bỏ qua kênh đó.
- Lỗi gửi chỉ ghi nhật ký (không lộ bí mật), không bao giờ làm hỏng thao tác tạo sự cố.
"""
from __future__ import annotations

import logging
import re
import smtplib
from collections.abc import Callable
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from html import escape
from typing import Any

import requests
from bson import ObjectId
from pymongo.database import Database

from app.security import crypto
from app.tenants.repo import SettingRepo

log = logging.getLogger("alerts")

KEY = "alert_channels"
TEXT_FIELDS = ("smtp_server", "smtp_port", "sender_email", "receiver_email", "telegram_chat_id")
SECRET_FIELDS = ("gmail_app_password", "telegram_bot_token")
DEFAULTS = {"smtp_server": "smtp.gmail.com", "smtp_port": "587"}
TIMEOUT = 15


class LoiKenh(Exception):
    pass


def parse_recipients(raw: object) -> list[str]:
    """Nhiều email nhận, phân cách phẩy / chấm phẩy / xuống dòng / khoảng trắng; bỏ trùng, giữ thứ tự (như hệ cũ)."""
    out: list[str] = []
    for p in re.split(r"[,;\s]+", str(raw or "").strip()):
        if p and "@" in p and p.lower() not in {x.lower() for x in out}:
            out.append(p)
    return out


# ====================================================================== cấu hình
def _raw(db: Database, tid: ObjectId) -> dict:
    d = SettingRepo(db, tid).find_one({"key": KEY}, {"value": 1})
    v = (d or {}).get("value")
    return v if isinstance(v, dict) else {}


def _secret(raw: dict, name: str, master: str) -> str:
    enc = raw.get(name + "_enc")
    if not enc:
        return ""
    try:
        return crypto.decrypt(str(enc), master)
    except Exception:
        log.warning("Không giải mã được %s (khoá chủ đã đổi?) — coi như chưa cấu hình", name)
        return ""


def load(db: Database, tid: ObjectId, master: str) -> dict:
    """Cấu hình ĐẦY ĐỦ (kể cả bí mật đã giải mã) — chỉ dùng nội bộ để gửi, KHÔNG trả ra API."""
    raw = _raw(db, tid)
    cfg = {k: str(raw.get(k) or DEFAULTS.get(k, "")).strip() for k in TEXT_FIELDS}
    for k in SECRET_FIELDS:
        cfg[k] = _secret(raw, k, master)
    return cfg


def public(db: Database, tid: ObjectId, master: str) -> dict:
    cfg = load(db, tid, master)
    out: dict[str, Any] = {k: cfg[k] for k in TEXT_FIELDS}
    for k in SECRET_FIELDS:
        out["has_" + k] = bool(cfg[k])
        out[k + "_mask"] = "*" * len(cfg[k])  # form hiện "đã lưu" mà không lộ nội dung (như hệ cũ)
    out["telegram_ready"] = bool(cfg["telegram_bot_token"] and cfg["telegram_chat_id"])
    out["email_ready"] = bool(cfg["sender_email"] and parse_recipients(cfg["receiver_email"])
                              and cfg["gmail_app_password"])
    return out


def save(db: Database, tid: ObjectId, master: str, data: dict, by: str) -> dict:
    """Trường văn bản: có trong `data` là ghi (kể cả rỗng). Bí mật: rỗng / thiếu = GIỮ NGUYÊN (chỉ ghi khi nhập mới);
    muốn xoá bí mật thì gửi `clear_<tên>: true`."""
    raw = _raw(db, tid)
    for k in TEXT_FIELDS:
        if k in data and data[k] is not None:
            raw[k] = str(data[k]).strip()[:500]
    if raw.get("smtp_port") and not str(raw["smtp_port"]).isdigit():
        raise LoiKenh("Cổng SMTP phải là số")
    for k in SECRET_FIELDS:
        v = str(data.get(k) or "").strip()
        if v:
            raw[k + "_enc"] = crypto.encrypt(v, master)
        elif data.get("clear_" + k):
            raw.pop(k + "_enc", None)
    raw["updated_by"], raw["updated_at"] = by, datetime.now().isoformat(timespec="seconds")
    SettingRepo(db, tid).update_one({"key": KEY}, {"$set": {"value": raw}}, upsert=True)
    return public(db, tid, master)


def _merge(cfg: dict, override: dict | None) -> dict:
    """Nút "Gửi thử" dùng giá trị ĐANG GÕ trên form (chưa lưu) nếu có — như hệ cũ."""
    out = dict(cfg)
    for k, v in (override or {}).items():
        if k in TEXT_FIELDS + SECRET_FIELDS and v not in (None, ""):
            out[k] = str(v).strip()
    return out


# ====================================================================== vận chuyển (test thay thế được)
def _post_telegram(token: str, chat_id: str, text: str) -> None:
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise LoiKenh(f"Telegram trả {r.status_code}: {r.text[:200]}")


def _smtp_send(host: str, port: int, sender: str, password: str, rcpts: list[str], subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")  # type: ignore[assignment] — tiêu đề có dấu phải mã hoá RFC 2047
    msg["From"] = sender
    msg["To"] = ", ".join(rcpts)
    server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT) if port == 465 else smtplib.SMTP(host, port, timeout=TIMEOUT)
    try:
        if port != 465:
            server.starttls()
        server.login(sender, password)
        server.sendmail(sender, rcpts, msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _port(cfg: dict) -> int:
    try:
        return int(cfg.get("smtp_port") or 587)
    except ValueError:
        return 587


def send_telegram(cfg: dict, text: str) -> None:
    if not (cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id")):
        raise LoiKenh("Thiếu token bot hoặc chat ID Telegram")
    _post_telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"], text)


def send_email(cfg: dict, subject: str, body: str) -> list[str]:
    rcpts = parse_recipients(cfg.get("receiver_email"))
    if not (cfg.get("sender_email") and rcpts and cfg.get("gmail_app_password")):
        raise LoiKenh("Thiếu email gửi / email nhận / mật khẩu ứng dụng")
    _smtp_send(cfg.get("smtp_server") or "smtp.gmail.com", _port(cfg), cfg["sender_email"], cfg["gmail_app_password"],
               rcpts, subject, body)
    return rcpts


def test(db: Database, tid: ObjectId, master: str, channel: str, override: dict | None = None) -> str:
    """Gửi thử ĐỒNG BỘ (người bấm chờ kết quả) — trả câu báo thành công, lỗi thì ném LoiKenh có lý do."""
    cfg = _merge(load(db, tid, master), override)
    try:
        if channel == "telegram":
            send_telegram(cfg, "Test Telegram từ IT Monitor 3.0 — nhận được tin này là kênh cảnh báo sự cố đã đạt.")
            return "Đã gửi tin Telegram thử."
        rcpts = send_email(cfg, "[TEST] Kiểm tra cấu hình Email", "Email kiểm tra từ IT Monitor 3.0.")
        return f"Đã gửi email thử tới {len(rcpts)} người nhận: {', '.join(rcpts)}."
    except LoiKenh:
        raise
    except Exception as e:  # lỗi mạng / SMTP từ chối đăng nhập… — nêu lý do cho người cấu hình
        raise LoiKenh(f"Lỗi gửi: {e}") from None


# ====================================================================== cảnh báo sự cố
def message(hostname: str, room: str, source: str, description: str,
            now: datetime | None = None) -> tuple[str, str, str]:
    """(văn bản Telegram HTML, tiêu đề email, thân email) — cùng bố cục với hệ cũ."""
    t = (now or datetime.now()).strftime("%d/%m/%Y %H:%M")
    tele = (f"🚨 <b>CẢNH BÁO THIẾT BỊ</b>\n\n💻 <b>Máy:</b> {escape(hostname)}\n🏫 <b>Phòng:</b> {escape(room)}\n"
            f"👤 <b>Nguồn:</b> {escape(source)}\n🕒 <b>Thời gian:</b> {t}\n\n⚠️ <b>NỘI DUNG:</b>\n{escape(description)}")
    subject = f"[SECURITY ALERT] CẢNH BÁO THIẾT BỊ: {hostname}"
    body = f"Máy: {hostname}\nPhòng: {room}\nNguồn: {source}\nThời gian: {t}\n\nNỘI DUNG: {description}"
    return tele, subject, body


def deliver(cfg: dict, hostname: str, room: str, source: str, description: str) -> dict:
    """Gửi một cảnh báo qua các kênh ĐÃ cấu hình. Trả {telegram|email: "ok"|"skip"|"<lỗi>"} (để test/nhật ký)."""
    tele, subject, body = message(hostname, room, source, description)
    out = {}
    if cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        try:
            send_telegram(cfg, tele)
            out["telegram"] = "ok"
        except Exception as e:
            out["telegram"] = str(e)[:200]
            log.warning("Cảnh báo Telegram cho %s lỗi: %s", hostname, type(e).__name__)
    else:
        out["telegram"] = "skip"
    if cfg.get("sender_email") and parse_recipients(cfg.get("receiver_email")) and cfg.get("gmail_app_password"):
        try:
            send_email(cfg, subject, body)
            out["email"] = "ok"
        except Exception as e:
            out["email"] = str(e)[:200]
            log.warning("Cảnh báo email cho %s lỗi: %s", hostname, type(e).__name__)
    else:
        out["email"] = "skip"
    return out


def _spawn(fn: Callable, *args: Any) -> None:
    from app.realtime.hub import socketio

    socketio.start_background_task(fn, *args)


def alert(db: Database, tid: ObjectId, master: str, *, hostname: str, room: str, source: str,
          description: str) -> None:
    """Cảnh báo một sự cố MỚI — đọc cấu hình ngay (đổi trên Desktop là có hiệu lực, không cần khởi động lại) rồi gửi
    ở tác vụ nền. Không cấu hình kênh nào thì không tạo tác vụ."""
    try:
        cfg = load(db, tid, master)
    except Exception:
        log.exception("Không đọc được cấu hình kênh cảnh báo")
        return
    if not (cfg["telegram_bot_token"] or cfg["gmail_app_password"]):
        return
    _spawn(deliver, cfg, hostname, room, source, description)
