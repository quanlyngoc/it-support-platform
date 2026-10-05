"""LocalFS — StorageService trên đĩa máy chủ (on-prem). Khoá `tenants/<tid>/<khu>/a/b.zip` ↔ tệp
`<gốc>\\tenants\\<tid>\\<khu>\\a\\b.zip` (gốc = DATA_DIR, dịch vụ đặt `D:\\ITSupportPlatformData`).
"""
from __future__ import annotations

import builtins
import contextlib
import hashlib
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO

from app.storage.base import KhongCo, ObjInfo, PutResult, QuaLon, Source, iter_chunks
from app.storage.keys import KhoaSai, parse, parse_prefix

# Tệp ghi dở do CHÍNH LocalFS đặt tên — không thể trùng tệp người dùng; liệt kê bỏ qua, worker dọn khi bị bỏ > 24 giờ
_PART = re.compile(r"^\.up-[0-9a-f]{32}\.part$")


class LocalFS:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    # ------------------------------------------------------------------ khoá → đường dẫn
    def _path(self, key: str) -> Path:
        parse(key)
        p = self.root.joinpath(*key.split("/"))
        # Lớp phòng thủ thứ hai (sau parse): đường dẫn thật phải nằm trong gốc, kể cả khi có junction/symlink
        if not p.resolve().is_relative_to(self.root):
            raise KhoaSai("khoá trỏ ra ngoài kho")
        return p

    def _info(self, key: str, p: Path) -> ObjInfo:
        st = p.stat()
        return ObjInfo(key, st.st_size, datetime.fromtimestamp(st.st_mtime, UTC))

    # ------------------------------------------------------------------ StorageService
    def put_stream(self, key: str, stream: Source, *, max_bytes: int | None = None) -> PutResult:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".up-{uuid.uuid4().hex}.part")
        h, n = hashlib.sha256(), 0
        try:
            with open(tmp, "wb") as f:
                for chunk in iter_chunks(stream):
                    n += len(chunk)
                    if max_bytes is not None and n > max_bytes:
                        raise QuaLon(f"tệp vượt giới hạn {max_bytes} byte")
                    h.update(chunk)
                    f.write(chunk)
            os.replace(tmp, p)  # nguyên tử trên cùng ổ đĩa
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        return PutResult(key, n, h.hexdigest())

    def get_stream(self, key: str) -> IO[bytes]:
        p = self._path(key)
        if not p.is_file():
            raise KhongCo(key)
        return open(p, "rb")  # noqa: SIM115 — nơi gọi (send_file / with) đóng

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if not p.is_file():
            return False
        p.unlink()
        self._prune(p.parent, self.root.joinpath(*key.split("/")[:3]))
        return True

    def move(self, src: str, dst: str) -> None:
        a, b = self._path(src), self._path(dst)
        if not a.is_file():
            raise KhongCo(src)
        b.parent.mkdir(parents=True, exist_ok=True)
        os.replace(a, b)
        self._prune(a.parent, self.root.joinpath(*src.split("/")[:3]))

    def list(self, prefix: str) -> builtins.list[ObjInfo]:
        base = self.root.joinpath(*parse_prefix(prefix))
        if not base.is_dir():
            return []
        out: builtins.list[ObjInfo] = []
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if _PART.match(name):
                    continue
                fp = Path(dirpath) / name
                with contextlib.suppress(OSError):  # tệp vừa bị xoá giữa lúc duyệt
                    out.append(self._info(fp.relative_to(self.root).as_posix(), fp))
        return sorted(out, key=lambda o: o.key)

    def stat(self, key: str) -> ObjInfo | None:
        p = self._path(key)
        return self._info(key, p) if p.is_file() else None

    def local_path(self, key: str) -> Path | None:
        p = self._path(key)
        return p if p.is_file() else None

    def purge_partials(self, older_than: timedelta, now: datetime | None = None) -> int:
        han = (now or datetime.now(UTC)).timestamp() - older_than.total_seconds()
        n = 0
        base = self.root / "tenants"
        if not base.is_dir():
            return 0
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if not _PART.match(name):
                    continue
                fp = Path(dirpath) / name
                try:
                    if fp.stat().st_mtime < han:
                        fp.unlink()
                        n += 1
                except OSError:
                    continue  # đang ghi / vừa xong → để lượt sau
        return n

    # ------------------------------------------------------------------ dọn thư mục rỗng
    @staticmethod
    def _prune(d: Path, stop: Path) -> None:
        """Xoá thư mục rỗng từ d ngược lên, DỪNG ở thư mục khu (`tenants/<tid>/<khu>` luôn giữ lại)."""
        while d != stop and d.is_relative_to(stop):
            try:
                d.rmdir()  # chỉ thành công khi rỗng
            except OSError:
                return
            d = d.parent
