"""Dọn tệp tạm cũ trong kho tệp agent v2 (<DATA_DIR>/<MÃ TỔ CHỨC>/) để không phình đĩa.

Hạn giữ theo hệ cũ (CHỈ ĐỌC: D:\\NetworkInventory\\app.py `cleanup_temp_files`): work 48 giờ · fs_tmp 48 giờ ·
collect 168 giờ (giáo viên kịp tải bài). `updates/` (bộ cài agent) KHÔNG bao giờ bị dọn.

Bài học hệ cũ (`_cleanup_duoc_phep_xoa`): luật "xoá mọi thứ quá hạn" suýt xoá nguyên CA THI vì trong kho thu bài có thư
mục ca thi thật. Vì vậy ở `work/` và `collect/` CHỈ xoá mục có tên là mã phiên do Core tự đặt (chuỗi hex) — mọi thứ khác
(người vận hành tự chép vào, thư mục ca thi sau này…) giữ nguyên. Không lỗi nào ở đây được làm dừng vòng nền.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

GIU_GIO = {"work": 48, "fs_tmp": 48, "collect": 168}
_MA_PHIEN = re.compile(r"^[0-9a-fA-F]{8,64}$")
_FS_TMP = re.compile(r"^[0-9a-fA-F]{8,64}_.+")  # <token>_<tên tệp> do store.py đặt


def _duoc_xoa(kho: str, ten: str) -> bool:
    if kho == "fs_tmp":
        return bool(_FS_TMP.match(ten))
    return bool(_MA_PHIEN.match(ten))


def don_tep_cu(root: Path, now: float | None = None) -> dict[str, int]:
    """Xoá mục quá hạn trong root/{work,fs_tmp,collect}. Trả số mục đã xoá theo kho."""
    now = time.time() if now is None else now
    da_xoa: dict[str, int] = {}
    for kho, gio in GIU_GIO.items():
        d = root / kho
        if not d.is_dir():
            continue
        han = now - gio * 3600
        n = 0
        for p in d.iterdir():
            try:
                if not _duoc_xoa(kho, p.name) or p.stat().st_mtime >= han:
                    continue
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink()
                n += 1
            except OSError:
                continue  # tệp đang mở (agent đang tải) → để lượt sau
        if n:
            da_xoa[kho] = n
    return da_xoa
