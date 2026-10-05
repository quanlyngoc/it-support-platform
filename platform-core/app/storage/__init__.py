"""Lưu trữ tệp (Sổ tay 7.1, CLAUDE.md §8).

- `StorageService` (base.py): put_stream / get_stream / delete / list — LocalFS hôm nay, S3 sau này.
- Khoá `tenants/<tenant_id>/{work,collected,thu,chat,report,temp,drive}/…` (keys.py).
- `TenantFiles` (files.py): kho của MỘT tổ chức + sổ `file_metadata` có hạn dọn; `sweeper.py` dọn mỗi giờ.
"""
from __future__ import annotations

from typing import Any

from bson import ObjectId

from app.storage.base import KhongCo, ObjInfo, PutResult, QuaLon, StorageService
from app.storage.files import TenantFiles
from app.storage.keys import AREAS, RETENTION, KhoaSai, key_for, safe_parts, safe_segment
from app.storage.local import LocalFS

__all__ = ["AREAS", "RETENTION", "KhoaSai", "KhongCo", "LocalFS", "ObjInfo", "PutResult", "QuaLon", "StorageService",
           "TenantFiles", "files_for", "key_for", "make_storage", "safe_parts", "safe_segment"]


def make_storage(data_dir: str) -> StorageService:
    """Kho mặc định: LocalFS tại DATA_DIR (khi có S3: chọn theo cấu hình ở đây, nơi gọi không đổi)."""
    return LocalFS(data_dir)


def files_for(app: Any, tenant_id: ObjectId) -> TenantFiles:
    return TenantFiles(app.extensions["itm_db"], tenant_id, app.extensions["storage"])
