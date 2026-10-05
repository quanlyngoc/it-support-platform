"""Dọn kho tệp theo hạn (Sổ tay 7.1) — mỗi giờ.

CHỈ xoá thứ Core ĐÃ GHI SỔ (dòng `file_metadata` scope=storage có `delete_after` đã qua) — KHÔNG BAO GIỜ quét đĩa rồi
xoá theo tuổi tệp. Bài học hệ cũ (`_cleanup_duoc_phep_xoa`): luật "xoá mọi thứ quá hạn" suýt xoá nguyên CA THI vì trong
kho thu bài có thư mục ca thi thật do người vận hành chép vào. Ngoại lệ duy nhất: tệp ghi dở `.up-<hex>.part` của chính
LocalFS bị bỏ quá 24 giờ (tên do Core tự đặt, không thể là tệp của người dùng).

Đi lần lượt TỪNG tổ chức qua repo_for (không truy vấn trần collection tenant-owned), và kiểm lại khoá thuộc đúng tổ
chức của dòng sổ trước khi xoá. Không lỗi nào ở đây được làm dừng vòng nền.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.database import Database

from app.storage.base import StorageService
from app.storage.files import SCOPE
from app.storage.keys import KhoaSai, parse
from app.tenants.repo import repo_for

log = logging.getLogger(__name__)
BATCH = 1000
PART_MAX_AGE = timedelta(hours=24)
EVERY_S = 3600.0


def sweep(db: Database, storage: StorageService, now: datetime | None = None, batch: int = BATCH) -> dict[str, int]:
    """Một lượt dọn. Trả số đếm khác 0: deleted · missing (sổ còn, tệp đã mất) · busy (tệp đang mở, để lượt sau) ·
    bad_key (khoá sai/chéo tổ chức — KHÔNG xoá, gỡ hạn để khỏi lặp) · partials."""
    now = now or datetime.now(UTC)
    out = {"deleted": 0, "missing": 0, "busy": 0, "bad_key": 0, "partials": 0}
    for t in db.tenants.find({}, {"_id": 1}):
        meta = repo_for(db, t["_id"], "file_metadata")
        rows = list(meta.find({"scope": SCOPE, "delete_after": {"$lte": now}}, {"key": 1}).limit(batch))
        for r in rows:
            key = r.get("key", "")
            try:
                parse(key, t["_id"])
            except KhoaSai:
                out["bad_key"] += 1
                log.warning("Dọn kho tệp: bỏ qua khoá sai %r của tổ chức %s", key, t["_id"])
                meta.update_one({"_id": r["_id"]}, {"$set": {"delete_after": None, "sweep_error": "khoá sai"}})
                continue
            try:
                existed = storage.delete(key)
            except OSError:
                out["busy"] += 1
                continue
            meta.delete_one({"_id": r["_id"]})
            out["deleted" if existed else "missing"] += 1
    out["partials"] = storage.purge_partials(PART_MAX_AGE, now)
    return {k: v for k, v in out.items() if v}


def start(app: Any, sio: Any) -> None:
    """Chạy vòng dọn mỗi giờ (gọi trong app.server.main; test gọi sweep trực tiếp)."""
    from app.legacy_adapter.writer import run_forever

    db, storage = app.extensions["itm_db"], app.extensions["storage"]

    def tick() -> dict[str, int]:
        r = sweep(db, storage)
        if r:
            log.info("Dọn kho tệp: %s", r)
        return r

    sio.start_background_task(run_forever, tick, sio.sleep, EVERY_S, "dọn kho tệp")
