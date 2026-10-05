"""Giao diện StorageService (Sổ tay 7.1, CLAUDE.md §8): LocalFS (on-prem) hôm nay, S3 (SeaweedFS / dịch vụ trong nước)
sau này — nơi gọi không biết bên dưới là gì.

Mọi hàm nhận KHOÁ (keys.py), không nhận đường dẫn đĩa: nơi gọi không bao giờ tự ghép đường dẫn.
Tệp đi dạng LUỒNG theo khối 256 KB, không nạp cả tệp vào RAM (bài học 10.8 hệ cũ: `files=` của requests làm phình RAM).
"""
from __future__ import annotations

import builtins
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Protocol

CHUNK = 256 * 1024

Source = IO[bytes] | Iterable[bytes]


@dataclass(frozen=True)
class ObjInfo:
    key: str
    size: int
    modified: datetime


@dataclass(frozen=True)
class PutResult:
    key: str
    size: int
    sha256: str


class KhongCo(FileNotFoundError):
    """Không có đối tượng mang khoá này."""


class QuaLon(ValueError):
    """Luồng dài hơn giới hạn cho phép (đã huỷ, không để lại tệp)."""


class StorageService(Protocol):
    def put_stream(self, key: str, stream: Source, *, max_bytes: int | None = None) -> PutResult:
        """Ghi NGUYÊN TỬ: người đang đọc không bao giờ thấy tệp ghi dở; lỗi giữa chừng không để lại gì."""
        ...

    def get_stream(self, key: str) -> IO[bytes]:
        """Luồng đọc (nơi gọi tự đóng). Không có → KhongCo."""
        ...

    def delete(self, key: str) -> bool:
        """Xoá; trả False nếu vốn không có. Tệp đang bị giữ (đang tải) → OSError, để lượt sau."""
        ...

    def list(self, prefix: str) -> builtins.list[ObjInfo]:
        """Mọi đối tượng dưới tiền tố `tenants/<tid>[/<khu>[/…]]` (không bao giờ liệt kê chéo tổ chức)."""
        ...

    def stat(self, key: str) -> ObjInfo | None: ...

    def local_path(self, key: str) -> Path | None:
        """Đường dẫn đĩa để phục vụ HTTP hiệu quả (send_file có Range/ETag); kho không phải đĩa → None."""
        ...

    def purge_partials(self, older_than: timedelta, now: datetime | None = None) -> int:
        """Xoá phần ghi dở bị bỏ (tiến trình chết giữa lúc nhận tệp). Trả số đã xoá."""
        ...


def iter_chunks(stream: Source) -> Iterator[bytes]:
    """Đọc từng khối từ tệp/luồng (có .read) hoặc từ bộ sinh bytes."""
    read = getattr(stream, "read", None)
    if read is not None:
        while chunk := read(CHUNK):
            yield chunk
        return
    for chunk in stream:  # type: ignore[union-attr]
        if chunk:
            yield bytes(chunk)
