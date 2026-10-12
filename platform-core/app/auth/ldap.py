"""Xác thực AD/LDAP bằng ldap3 (đặc tả §64: chỉ Core nói chuyện với LDAP).

Giữ cách kết nối đã chạy ổn của hệ cũ (CHỈ ĐỌC: D:\\NetworkInventory\\ldap_auth.py `_server_from_cfg`): `server` nhận
`host`, `ldap://host:389` hoặc `ldaps://host:636`; LDAPS ÉP TLS 1.2 (DC Windows mới tắt TLS cũ → reset bắt tay, WinError
10054) và KHÔNG kiểm chứng chỉ (DC nội bộ, chứng chỉ tự cấp) — HOAN_BAO_MAT: kiểm chứng chỉ khi có CA nội bộ.
Bảng chẩn đoán lỗi (`diag`) chép từ `_ldap_diag` của hệ cũ: nêu ĐÚNG mã phụ AD "data XXX" thay vì "sai thông tin".
"""
from __future__ import annotations

import re
import ssl
from typing import Any


def _server(server_url: str) -> Any:
    from ldap3 import Server, Tls

    raw = (server_url or "").strip()
    use_ssl = raw.lower().startswith("ldaps://")
    host = re.sub(r"^ldaps?://", "", raw, flags=re.IGNORECASE).rstrip("/")
    port = 636 if use_ssl else 389
    if ":" in host:
        h, p = host.rsplit(":", 1)
        if p.isdigit():
            host, port = h, int(p)
    tls = Tls(validate=ssl.CERT_NONE, version=ssl.PROTOCOL_TLSv1_2) if use_ssl else None
    return Server(host, port=port, use_ssl=use_ssl, tls=tls, connect_timeout=5)


def principal_of(principal: str, domain: str) -> str:
    """Tên gõ không có @ / \\ → ghép @domain (hệ cũ `_norm_ad_account`)."""
    p = (principal or "").strip()
    d = (domain or "").strip().lstrip("@")
    return p if ("@" in p or "\\" in p or not d) else f"{p}@{d}"


def ldap_bind(cfg: dict, principal: str, password: str) -> bool:
    """Bind thử bằng tài khoản người dùng. cfg: {'ldap.server': 'ldaps://...', 'ldap.domain': 'phenikaamec.local'}."""
    if not password:  # bind với mật khẩu rỗng = anonymous bind, LUÔN thành công -> phải chặn
        return False
    server_url = (cfg.get("ldap.server") or "").strip()
    if not server_url:
        return False
    try:
        from ldap3 import Connection

        conn = Connection(_server(server_url), user=principal_of(principal, cfg.get("ldap.domain") or ""),
                          password=password, receive_timeout=5)
        ok = bool(conn.bind())
        conn.unbind()
        return ok
    except Exception:
        return False


def test_bind(server_url: str, user: str, password: str) -> tuple[bool, str]:
    """Nút "Kiểm tra kết nối": bind bằng tài khoản (dịch vụ hoặc người thử) → (đạt?, thông báo tiếng Việt)."""
    if not (server_url or "").strip():
        return False, "Thiếu địa chỉ máy chủ LDAP."
    if not user or not password:
        return False, "Thiếu tài khoản hoặc mật khẩu để thử bind."
    try:
        from ldap3 import Connection

        conn = Connection(_server(server_url), user=user, password=password, receive_timeout=5)
        if conn.bind():
            conn.unbind()
            return True, f"Kết nối AD thành công (bind OK bằng {user})."
        return False, diag(result=conn.result, last_error=str(conn.last_error or ""))
    except Exception as e:
        return False, diag(exc_text=str(e))


_AD = {
    "52e": "SAI MẬT KHẨU (tài khoản đúng). Nhập đúng mật khẩu thật của tài khoản AD.",
    "525": "KHÔNG TÌM THẤY tài khoản: sai UPN/tên đăng nhập. Thử dạng DOMAIN\\user.",
    "530": "Không được phép đăng nhập vào thời điểm này (giới hạn giờ đăng nhập).",
    "531": "Không được phép đăng nhập từ máy này (giới hạn workstation).",
    "532": "MẬT KHẨU HẾT HẠN: cần đặt lại mật khẩu cho tài khoản trong AD.",
    "533": "Tài khoản bị VÔ HIỆU HÓA (disabled): hãy bật lại trong AD.",
    "568": "Đạt giới hạn số phiên đăng nhập đồng thời.",
    "701": "Tài khoản ĐÃ HẾT HẠN (account expired).",
    "773": "Tài khoản bắt buộc ĐỔI MẬT KHẨU lần đầu: bỏ tick 'User must change password at next logon'.",
    "775": "Tài khoản bị KHÓA (locked out): mở khóa trong AD rồi nhập đúng mật khẩu — đừng thử sai nhiều lần.",
}


def diag(result: dict | None = None, last_error: str = "", exc_text: str = "") -> str:
    msg = str((result or {}).get("message") or "")
    blob = f"{exc_text} {last_error} {msg}".lower()
    m = re.search(r"data ([0-9a-f]{1,4})\b", blob)
    if m:
        code = m.group(1)
        return f"[data {code}] " + _AD.get(code, "Lỗi xác thực AD (mã chưa có trong danh sách — tra tài liệu AD).")
    if "10054" in blob or "ssl wrapping" in blob or ("ssl" in blob and "wrap" in blob):
        return ("[SSL] Lỗi bắt tay SSL/TLS: máy chủ reset kết nối. Có thể DC chưa bật LDAPS đúng cách hoặc lệch phiên "
                "bản TLS. Thử ldap://<ip>:389 để kiểm chứng.")
    if "certificate verify failed" in blob:
        return "[SSL-CERT] Chứng chỉ máy chủ không hợp lệ/không tin cậy."
    if "timed out" in blob or "timeout" in blob or "10060" in blob:
        return "[TIMEOUT] Quá thời gian kết nối: sai IP/cổng, hoặc tường lửa chặn cổng."
    if "10061" in blob or "refused" in blob:
        return "[REFUSED] Bị từ chối kết nối: sai cổng hoặc dịch vụ LDAP không chạy trên máy chủ đó."
    if "getaddrinfo" in blob or "11001" in blob or "no such host" in blob or "name or service not known" in blob:
        return "[DNS] Không phân giải được máy chủ: kiểm tra IP/tên máy trong địa chỉ LDAP."
    desc = str((result or {}).get("description") or "").lower()
    if "strongerauthrequired" in desc:
        return "[strongerAuthRequired] Máy chủ bắt buộc kết nối bảo mật: hãy dùng ldaps://<ip>:636."
    if "unwillingtoperform" in desc:
        return "[unwillingToPerform] Máy chủ từ chối thực hiện (chính sách hoặc tài khoản bị hạn chế)."
    if "invalidcredentials" in desc:
        return "[invalidCredentials] Sai thông tin đăng nhập (không kèm mã phụ chi tiết)."
    raw = last_error or str((result or {}).get("description") or "") or exc_text or "không rõ"
    return f"[?] Lỗi không xác định: {raw[:300]}"
