"""Lệnh quản trị tổ chức (bước 2.7 của Sổ tay).

    uv run python -m app.tenants.cli create --code PHENIKAA --name "Truong Dai hoc Phenikaa"
    uv run python -m app.tenants.cli create-admin --tenant PHENIKAA --username admin
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.db.client import get_db
from app.tenants import service
from app.utils.console import utf8_stdio


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="app.tenants.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="Tạo tổ chức + policy Super Admin")
    c.add_argument("--code", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--timezone", default="Asia/Ho_Chi_Minh")
    a = sub.add_parser("create-admin", help="Tạo tài khoản Local gắn policy Super Admin")
    a.add_argument("--tenant", required=True)
    a.add_argument("--username", required=True)
    a.add_argument("--display-name", default="")
    a.add_argument("--password-stdin", action="store_true", help="Đọc mật khẩu từ stdin (dùng cho script)")
    args = ap.parse_args(argv)

    db = get_db()
    try:
        if args.cmd == "create":
            t = service.create_tenant(db, args.code, args.name, args.timezone)
            print(f"Đã tạo tổ chức {t['code']} ({t['_id']})")
        else:
            t = service.get_tenant_by_code(db, args.tenant)
            if not t:
                print(f"Không có tổ chức {args.tenant}", file=sys.stderr)
                return 2
            pw = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("Mật khẩu: ")
            pid = service.super_admin_policy_id(db, t["_id"])
            u = service.create_user(db, t["_id"], args.username, password=pw, display_name=args.display_name,
                                    policy_ids=[pid])
            print(f"Đã tạo Super Admin {u['username']} cho {t['code']}")
    except service.TenantError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
