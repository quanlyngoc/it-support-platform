"""Khung "Máy chủ" của trình quản lý tệp (Sổ tay 7.2) — kho tệp RIÊNG của tổ chức (khu `drive`), chỉ Super Admin.

Hệ cũ cho Super Admin duyệt ổ đĩa THẬT của máy chủ (`/api/fs/srv`). Core là SaaS nhiều tổ chức trên cùng máy chủ → làm
vậy là lộ dữ liệu chéo; thay bằng kho riêng `tenants/<tid>/drive/…`. Giữ NGUYÊN tên lệnh + dạng kết quả của hệ cũ
(list / mkdir / delete / recycle / rename / copy / stage / land, `{ok, error, …}`) → Desktop dùng MỘT đường code cho mọi
nguồn (khung máy trạm đi socket, khung máy chủ đi HTTP).

- Đường dẫn tương đối, phân cách `\\` như khung máy trạm, gốc = "". Tên phải hợp lệ NGUYÊN VẸN (không tự sửa ngầm).
- Thư mục là ngầm định (suy từ khoá); thư mục rỗng giữ bằng tệp đánh dấu `.folder` (ẩn khỏi danh sách).
- So trùng tên KHÔNG phân biệt hoa/thường (NTFS coi `Bai` và `bai` là một — để hai dòng sổ trỏ cùng một tệp là mất dữ
  liệu khi xoá một trong hai).
- Xoá mềm (recycle) = chuyển vào thư mục `Thùng rác` ở gốc, tự dọn sau 30 ngày (như THU_trash hệ cũ); xoá trong Thùng
  rác = xoá hẳn; chuyển ra khỏi Thùng rác = hết hạn dọn.
- stage: bày tệp/thư mục ra token cho máy trạm tải (`/fs_serve/<token>`); thư mục nén .zip (theo luồng). land: tệp máy
  trạm vừa nộp (`/fs_recv_raw`) hạ vào thư mục đích; gói .zip giải nén từng mục, đường dẫn trong gói qua `safe_parts`
  (chống zip-slip).
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage import TenantFiles, safe_parts, safe_segment
from app.storage.base import CHUNK, Source

TRASH = "Thùng rác"
TRASH_TTL = timedelta(days=30)
MARK = ".folder"


class LoiKho(Exception):
    """Thao tác không làm được — trả `{ok: false, error}` như hệ cũ."""


def split(path: object) -> list[str]:
    """`De thi\\Ca 1` (hoặc `/`) → các đoạn; đoạn nào không hợp lệ NGUYÊN VẸN → LoiKho."""
    segs = [s for s in str(path or "").replace("/", "\\").split("\\") if s != ""]
    for s in segs:
        if s in (".", "..", MARK) or safe_segment(s) != s:
            raise LoiKho(f"Tên không hợp lệ: {s!r} (không dùng \\ / : * ? \" < > | và không kết thúc bằng dấu chấm)")
    return segs


def one(name: object) -> str:
    segs = split(name)
    if len(segs) != 1:
        raise LoiKho("Cần đúng một tên (không chứa \\ hoặc /)")
    return segs[0]


def _ts(dt: Any) -> int:
    if not isinstance(dt, datetime):
        return 0
    return int((dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp())


class Drive:
    def __init__(self, kho: TenantFiles):
        self.kho = kho

    # ------------------------------------------------------------------ khoá + tra cứu
    def _key(self, segs: list[str]) -> str:
        return self.kho.key("drive", *segs)

    def _prefix(self, segs: list[str]) -> str:
        return "/".join(["tenants", str(self.kho.tid), "drive", *segs]) + "/"

    def _docs(self, segs: list[str]) -> list[dict]:
        return self.kho.list("drive", *segs)

    def _is_file(self, segs: list[str]) -> bool:
        return bool(segs) and self.kho.exists(self._key(segs))

    def _is_dir(self, segs: list[str]) -> bool:
        return not segs or bool(self._docs(segs))

    def _children(self, segs: list[str]) -> dict[str, str]:
        """Tên con (chữ thường) → tên thật, của thư mục `segs`."""
        if segs and not self._is_dir(segs):
            return {}
        return {it["name"].lower(): it["name"] for it in self._items(segs)}

    def _same(self, segs: list[str]) -> str | None:
        """Tên thật của mục trùng tên (không phân biệt hoa/thường) với `segs` trong thư mục cha, nếu có."""
        return self._children(segs[:-1]).get(segs[-1].lower()) if segs else None

    def _free(self, parent: list[str], name: str) -> str:
        """Tên chưa ai dùng trong `parent`: `bai.docx` → `bai (2).docx`…"""
        taken = self._children(parent)
        if name.lower() not in taken:
            return name
        stem, ext = os.path.splitext(name)
        for i in range(2, 1000):
            cand = f"{stem} ({i}){ext}"
            if cand.lower() not in taken:
                return cand
        raise LoiKho("Quá nhiều mục trùng tên")

    @staticmethod
    def _ttl(segs: list[str]) -> timedelta | None:
        return TRASH_TTL if segs and segs[0] == TRASH else None

    def _items(self, segs: list[str]) -> list[dict]:
        pre = self._prefix(segs)
        files: dict[str, dict] = {}
        dirs: dict[str, dict] = {}
        for d in self._docs(segs):
            rel = d["key"][len(pre):].split("/")
            t = _ts(d.get("updated_at"))
            if len(rel) == 1:
                if rel[0] != MARK:
                    files[rel[0]] = {"name": rel[0], "type": "file", "size": int(d.get("size") or 0), "mtime": t}
            else:
                cur = dirs.setdefault(rel[0], {"name": rel[0], "type": "dir", "size": 0, "mtime": 0})
                cur["mtime"] = max(cur["mtime"], t)

        def by_name(x: dict) -> str:
            return x["name"].lower()

        return sorted(dirs.values(), key=by_name) + sorted(files.values(), key=by_name)

    def _mark(self, segs: list[str], by: str) -> None:
        if segs and not self._is_dir(segs):
            self.kho.save("drive", [*segs, MARK], io.BytesIO(b""), by=by, ttl=self._ttl(segs))

    # ------------------------------------------------------------------ lệnh
    def list(self, path: str) -> tuple[str, list[dict]]:
        segs = split(path)
        if segs and not self._is_dir(segs):
            raise LoiKho("Thư mục không tồn tại")
        return "\\".join(segs), self._items(segs)

    def mkdir(self, path: str, name: str, by: str = "") -> str:
        segs = [*split(path), one(name)]
        real = self._same(segs)
        if real is not None:
            if self._is_file([*segs[:-1], real]):
                raise LoiKho(f"Đã có tệp tên {real!r}")
            return real  # như os.makedirs(exist_ok=True) của hệ cũ
        self._mark(segs, by)
        return segs[-1]

    def delete(self, target: str) -> None:
        segs = split(target)
        if not segs:
            raise LoiKho("Không xoá được thư mục gốc")
        if self._is_file(segs):
            self.kho.delete(self._key(segs))
        elif not self.kho.delete_under("drive", *segs):
            raise LoiKho("Không tồn tại")

    def recycle(self, target: str) -> str:
        segs = split(target)
        if not segs:
            raise LoiKho("Không xoá được thư mục gốc")
        if segs[0] == TRASH:  # đã ở trong Thùng rác (hoặc chính Thùng rác) → xoá hẳn
            self.delete(target)
            return ""
        name = self._free([TRASH], segs[-1])
        self._move(segs, [TRASH, name])
        return name

    def rename(self, src: str, dst: str) -> None:
        self._move(split(src), split(dst))

    def copy(self, src: str, dst: str, by: str = "") -> None:
        a, b = split(src), split(dst)
        self._check_pair(a, b)
        if self._is_file(a):
            self.kho.copy(self._key(a), self._key(b), by=by, ttl=self._ttl(b))
            return
        docs = self._docs(a)
        if not docs:
            raise LoiKho("Không tồn tại")
        pre = self._prefix(a)
        for d in docs:
            self.kho.copy(d["key"], self.kho.key("drive", *b, d["key"][len(pre):]), by=by, ttl=self._ttl(b))

    def _check_pair(self, a: list[str], b: list[str]) -> None:
        if not a or not b:
            raise LoiKho("Thiếu src/dst")
        if [s.lower() for s in b[:len(a)]] == [s.lower() for s in a] and len(b) > len(a):
            raise LoiKho("Không chuyển/chép thư mục vào chính nó")
        real = self._same(b)
        chinh_no = len(a) == len(b) and a[:-1] == b[:-1] and real == a[-1]  # chỉ đổi hoa/thường của chính nó
        if real is not None and not chinh_no:
            raise LoiKho(f"Đích đã có mục tên {real!r}")

    def _move(self, a: list[str], b: list[str]) -> None:
        if a == b:
            return
        self._check_pair(a, b)
        ttl = self._ttl(b)
        if self._is_file(a):
            self.kho.move(self._key(a), self._key(b), ttl=ttl)
            return
        docs = self._docs(a)
        if not docs:
            raise LoiKho("Không tồn tại")
        pre = self._prefix(a)
        for d in docs:
            self.kho.move(d["key"], self.kho.key("drive", *b, d["key"][len(pre):]), ttl=ttl)

    # ------------------------------------------------------------------ máy bạn ↔ máy chủ
    def upload(self, path: str, name: object, stream: Source, by: str = "") -> dict:
        parent = split(path)
        nm = safe_segment(name)
        real = self._same([*parent, nm])
        if real is not None and self._is_dir([*parent, real]):
            raise LoiKho(f"Đã có thư mục tên {real!r}")
        segs = [*parent, real or nm]  # trùng tên tệp (kể cả khác hoa/thường) → ghi đè đúng tệp đó, như hệ cũ
        return self.kho.save("drive", segs, stream, name=segs[-1], by=by, ttl=self._ttl(segs))

    def file(self, path: str) -> dict:
        segs = split(path)
        doc = self.kho.get(self._key(segs)) if segs else None
        if doc is None:
            raise LoiKho("Không phải tệp hoặc không tồn tại")
        return doc

    # ------------------------------------------------------------------ máy chủ ↔ máy trạm
    def stage(self, target: str, new_token: Callable[[], str], set_push: Callable[[str, str], None],
              by: str = "") -> dict:
        segs = split(target)
        if not segs:
            raise LoiKho("Chọn một tệp hoặc thư mục")
        if self._is_file(segs):  # KHÔNG chép — máy trạm tải thẳng từ kho, như hệ cũ
            tok = new_token()
            set_push(tok, self._key(segs))
            return {"token": tok, "filename": segs[-1], "zipped": False}
        docs = self._docs(segs)
        if not docs:
            raise LoiKho("Không tồn tại")
        tok = new_token()
        pre = self._prefix(segs)
        with tempfile.TemporaryFile() as tmp:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                for d in docs:
                    rel = d["key"][len(pre):]
                    if rel == MARK:
                        continue
                    if rel.endswith("/" + MARK):
                        z.writestr(rel[: -len(MARK)], b"")  # thư mục rỗng vẫn có mặt khi giải nén
                        continue
                    with self.kho.open(d["key"]) as f, z.open(rel, "w", force_zip64=True) as w:
                        shutil.copyfileobj(f, w, CHUNK)
            tmp.seek(0)
            doc = self.kho.save("temp", ["fs", safe_segment(f"{tok}_{segs[-1]}.zip")], tmp, name=f"{segs[-1]}.zip",
                                by=by)
        set_push(tok, doc["key"])
        return {"token": tok, "filename": segs[-1], "zipped": True}

    def land(self, pulled: dict, folder: str, filename: object, zipped: bool, by: str = "") -> str:
        """Hạ tệp máy trạm vừa nộp (dòng sổ `pulled`) vào thư mục `folder`. Trả tên thật đã dùng."""
        parent = split(folder)
        if parent and self._is_file(parent):
            raise LoiKho("Đích không phải thư mục")
        ttl = self._ttl(parent)
        if not zipped:
            name = self._free(parent, safe_segment(filename))
            self.kho.move(pulled["key"], self._key([*parent, name]), ttl=ttl)
            return name
        name = safe_segment(filename)
        real = self._same([*parent, name])
        if real is not None and self._is_file([*parent, real]):
            name = self._free(parent, name)
        else:
            name = real or name  # thư mục đã có → giải nén chồng vào, như extractall của hệ cũ
        base = [*parent, name]
        local = self.kho.local_path(pulled["key"])
        with (open(local, "rb") if local else self._spool(pulled["key"])) as src, zipfile.ZipFile(src) as z:
            for info in z.infolist():
                parts = safe_parts(info.filename)
                if info.is_dir():
                    self._mark([*base, *parts], by)
                    continue
                with z.open(info) as f:
                    self.kho.save("drive", [*base, *parts], f, by=by, ttl=ttl)
        self._mark(base, by)
        self.kho.delete(pulled["key"])
        return name

    def _spool(self, key: str):
        tmp = tempfile.TemporaryFile()
        with self.kho.open(key) as f:
            shutil.copyfileobj(f, tmp, CHUNK)
        tmp.seek(0)
        return tmp
