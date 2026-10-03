"""Xuất đặc tả OpenAPI của Core ra tệp JSON — Desktop sinh kiểu TypeScript từ đây (Sổ tay 4.5), KHÔNG cần chạy server
hay kết nối CSDL (dựng app trên mongomock — công cụ phát triển, chỉ có trong môi trường dev).

    uv run python -m app.openapi_dump ../desktop-app/src/api-client/openapi.json
"""
from __future__ import annotations

import json
import pathlib
import sys


def spec() -> dict:
    import mongomock

    from app.config.settings import Settings
    from app.server import create_app

    app = create_app(db=mongomock.MongoClient()["openapi"], settings=Settings(MONGO_URI="mongodb://khong-dung"),
                     async_mode="threading")
    return app.spec  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # stdout bị ống dẫn (pnpm gen:api) trên Windows mặc định cp1252 → chữ Việt nổ UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    text = json.dumps(spec(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if argv:
        out = pathlib.Path(argv[0])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"Đã ghi {out} ({len(text)} byte)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
