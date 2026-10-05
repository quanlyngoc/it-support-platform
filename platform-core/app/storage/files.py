"""Kho tệp của MỘT tổ chức = StorageService + sổ ghi `file_metadata` (scope="storage").

Mỗi tệp Core ghi đều có một dòng sổ: khoá, khu, tên hiển thị, cỡ, SHA-256, ai ghi, `delete_after` (hạn dọn theo khu).
Worker (`sweeper.py`) CHỈ xoá theo sổ này.

⚠️ Hạn dọn nằm ở `delete_after`, KHÔNG dùng `expires_at`: `file_metadata.expires_at` có TTL index (cho token truyền tệp)
→ MongoDB tự xoá DÒNG SỔ đúng hạn, worker không còn thấy để xoá TỆP → tệp mồ côi trên đĩa mãi mãi.

Ghi theo 3 nhịp để không bao giờ có tệp nằm ngoài sổ: (1) giữ chỗ dòng sổ `status=uploading` hạn 1 ngày → (2) ghi tệp
(nguyên tử) → (3) chốt dòng sổ `status=ok` + hạn thật. Lỗi ở (2) → bỏ dòng giữ chỗ; tiến trình chết giữa chừng → worker
dọn sau 1 ngày.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO

from bson import ObjectId
from pymongo.database import Database

from app.storage.base import Source, StorageService
from app.storage.keys import RETENTION, key_for, parse, parse_prefix
from app.tenants.repo import repo_for

SCOPE = "storage"
PENDING = timedelta(days=1)
_HIDE = {"_id": 0, "tenant_id": 0}


class TenantFiles:
    def __init__(self, db: Database, tenant_id: ObjectId, storage: StorageService,
                 now: Callable[[], datetime] | None = None):
        self.tid = tenant_id
        self.storage = storage
        self.meta = repo_for(db, tenant_id, "file_metadata")
        self._now = now or (lambda: datetime.now(UTC))

    def key(self, area: str, *parts: str) -> str:
        return key_for(self.tid, area, *parts)

    # ------------------------------------------------------------------ ghi
    def save(self, area: str, parts: str | Sequence[str], stream: Source, *, name: str = "", by: str = "",
             ttl: timedelta | None = None, max_bytes: int | None = None, extra: dict | None = None) -> dict:
        """Ghi tệp vào khu `area` (đường dẫn con `parts`, các đoạn ĐÃ an toàn). `ttl` None = hạn mặc định của khu."""
        key = self.key(area, *([parts] if isinstance(parts, str) else parts))
        q = {"scope": SCOPE, "key": key}
        now = self._now()
        held = self.meta.update_one(q, {"$setOnInsert": {**q, "area": area, "status": "uploading", "created_at": now,
                                                         "delete_after": now + PENDING}}, upsert=True)
        try:
            put = self.storage.put_stream(key, stream, max_bytes=max_bytes)
        except BaseException:
            if held.upserted_id is not None:
                self.meta.delete_one({"_id": held.upserted_id})
            raise
        now = self._now()
        keep = ttl if ttl is not None else RETENTION.get(area)
        doc = {"area": area, "name": name or key.rsplit("/", 1)[-1], "size": put.size, "sha256": put.sha256,
               "by": by, "status": "ok", "updated_at": now, "delete_after": now + keep if keep else None,
               **(extra or {})}
        self.meta.update_one(q, {"$set": doc})
        out = self.get(key)
        assert out is not None
        return out

    # ------------------------------------------------------------------ đọc
    def get(self, key: str) -> dict | None:
        """Dòng sổ của tệp đã ghi xong (thuộc ĐÚNG tổ chức này)."""
        parse(key, self.tid)
        return self.meta.find_one({"scope": SCOPE, "key": key, "status": "ok"}, _HIDE)

    def open(self, key: str) -> IO[bytes]:
        parse(key, self.tid)
        return self.storage.get_stream(key)

    def local_path(self, key: str) -> Path | None:
        parse(key, self.tid)
        return self.storage.local_path(key)

    def list(self, area: str, *parts: str) -> list[dict]:
        """Các tệp đã ghi xong dưới `<khu>/<parts…>` theo sổ, sắp theo khoá."""
        segs = parse_prefix("/".join(["tenants", str(self.tid), area, *parts]), self.tid)
        pre = "/".join(segs) + "/"
        return list(self.meta.find({"scope": SCOPE, "status": "ok", "key": {"$regex": "^" + re.escape(pre)}},
                                   _HIDE).sort("key", 1))

    # ------------------------------------------------------------------ xoá chủ động
    def delete(self, key: str) -> bool:
        parse(key, self.tid)
        existed = self.storage.delete(key)
        self.meta.delete_one({"scope": SCOPE, "key": key})
        return existed

    def delete_under(self, area: str, *parts: str) -> int:
        """Xoá mọi tệp dưới `<khu>/<parts…>` (vd. cả một phiên thu bài). Trả số tệp đã xoá."""
        return sum(self.delete(d["key"]) for d in self.list(area, *parts))
