"""Xác thực AD/LDAP bằng ldap3 (đặc tả §64: chỉ Core nói chuyện với LDAP)."""
from __future__ import annotations


def ldap_bind(cfg: dict, principal: str, password: str) -> bool:
    """Bind thử bằng tài khoản người dùng. cfg: {'ldap.server': 'ldaps://...', 'ldap.domain': 'phenikaamec.local'}."""
    if not password:  # bind với mật khẩu rỗng = anonymous bind, LUÔN thành công -> phải chặn
        return False
    server_url = (cfg.get("ldap.server") or "").strip()
    if not server_url:
        return False
    domain = (cfg.get("ldap.domain") or "").strip()
    user = principal if ("@" in principal or "\\" in principal or not domain) else f"{principal}@{domain}"
    try:
        from ldap3 import Connection, Server

        srv = Server(server_url, use_ssl=server_url.lower().startswith("ldaps://"), connect_timeout=5)
        conn = Connection(srv, user=user, password=password, auto_bind=True, receive_timeout=5)
        conn.unbind()
        return True
    except Exception:
        return False
