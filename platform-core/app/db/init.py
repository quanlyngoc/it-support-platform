"""Khởi tạo CSDL: collection + validator → index → seed. Chạy lại nhiều lần an toàn.

    uv run python -m app.db.init
"""
from __future__ import annotations

from pymongo.database import Database

from app.db import indexes, seeds, validators


def init_database(db: Database) -> dict:
    return {
        "collections": validators.apply(db),
        "indexes": indexes.ensure(db),
        "permissions": seeds.seed(db),
    }


def main() -> None:
    from app.db.client import get_db
    from app.utils.console import utf8_stdio

    utf8_stdio()
    db = get_db()
    print("Khởi tạo CSDL", db.name, "→", init_database(db))


if __name__ == "__main__":
    main()
