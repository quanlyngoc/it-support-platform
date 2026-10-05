"""Khoá lưu trữ (Sổ tay 7.1): `tenants/<tenant_id>/<khu>/<…>` — ranh giới tổ chức nằm NGAY trong khoá.

Luật (kiểm ở MỌI thao tác của kho, không tin nơi gọi):
- bắt đầu bằng `tenants/<24 hex>/<khu>/`, khu ∈ AREAS, sau khu có ít nhất một đoạn;
- phân cách CHỈ bằng `/`; cấm `..`, `.`, đoạn rỗng, `\\`, ký tự điều khiển, ký tự Windows cấm (`<>:"|?*`);
- cấm đoạn kết thúc bằng dấu cách / dấu chấm (Windows tự cắt → hai khoá khác nhau trỏ CÙNG một tệp) và tên thiết bị
  (`CON`, `NUL`, `COM1`… kể cả có đuôi như `con.txt`);
- có tenant_id mong đợi thì khoá PHẢI thuộc đúng tổ chức đó.
Tên do người dùng / agent gửi lên → `safe_segment` / `safe_parts` trước, rồi mới dựng khoá bằng `key_for`.
"""
from __future__ import annotations

import os
import re
from datetime import timedelta

from bson import ObjectId

AREAS = ("work", "collected", "thu", "chat", "report", "temp", "drive")
# `drive` (Sổ tay 7.2): "Máy chủ" trong trình quản lý tệp = kho tệp RIÊNG của tổ chức (KHÔNG phải ổ đĩa thật của máy
# chủ — SaaS nhiều tổ chức dùng chung máy chủ). Giữ vô hạn; riêng thư mục "Thùng rác" có hạn 30 ngày (files/drive.py).
# Hạn giữ như hệ cũ (cleanup_temp_files): tạm + giao bài 48 giờ, bài thu 168 giờ (giáo viên kịp tải).
# Khu không có trong bảng (thu, chat, report) giữ tới khi bị xoá chủ động.
RETENTION: dict[str, timedelta] = {"temp": timedelta(hours=48), "work": timedelta(hours=48),
                                   "collected": timedelta(hours=168)}
MAX_KEY = 900
_TID = re.compile(r"^[0-9a-f]{24}$")
_BAD = re.compile(r'[<>:"|?*\\\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class KhoaSai(ValueError):
    """Khoá lưu trữ sai luật hoặc thuộc tổ chức khác."""


def _reserved(s: str) -> bool:
    return s.split(".")[0].strip().lower() in _RESERVED


def _seg_ok(s: str) -> bool:
    return (bool(s) and len(s) <= 255 and s not in (".", "..") and not _BAD.search(s) and s[-1] not in " ."
            and not _reserved(s))


def parse(key: object, tenant_id: ObjectId | str | None = None) -> tuple[str, str, list[str]]:
    """Kiểm khoá; trả (tenant_id dạng hex, khu, các đoạn sau khu)."""
    if not isinstance(key, str) or not key or len(key) > MAX_KEY:
        raise KhoaSai("khoá rỗng hoặc quá dài")
    segs = key.split("/")
    if len(segs) < 4 or segs[0] != "tenants" or not _TID.match(segs[1]) or segs[2] not in AREAS:
        raise KhoaSai(f"khoá phải có dạng tenants/<tenant_id>/<{'|'.join(AREAS)}>/…: {key!r}")
    if not all(_seg_ok(s) for s in segs[3:]):
        raise KhoaSai(f"khoá có đoạn không hợp lệ: {key!r}")
    if tenant_id is not None and segs[1] != str(tenant_id):
        raise KhoaSai("khoá thuộc tổ chức khác")
    return segs[1], segs[2], segs[3:]


def parse_prefix(prefix: object, tenant_id: ObjectId | str | None = None) -> list[str]:
    """Tiền tố để liệt kê: `tenants/<tid>[/<khu>[/…]]` (có hay không có `/` cuối). Luôn phải có tổ chức."""
    if not isinstance(prefix, str) or not prefix or len(prefix) > MAX_KEY:
        raise KhoaSai("tiền tố rỗng hoặc quá dài")
    segs = prefix.removesuffix("/").split("/")
    if len(segs) < 2 or segs[0] != "tenants" or not _TID.match(segs[1]):
        raise KhoaSai(f"tiền tố phải bắt đầu bằng tenants/<tenant_id>: {prefix!r}")
    if len(segs) > 2 and segs[2] not in AREAS:
        raise KhoaSai(f"khu lạ: {segs[2]!r}")
    if not all(_seg_ok(s) for s in segs[3:]):
        raise KhoaSai(f"tiền tố có đoạn không hợp lệ: {prefix!r}")
    if tenant_id is not None and segs[1] != str(tenant_id):
        raise KhoaSai("tiền tố thuộc tổ chức khác")
    return segs


def key_for(tenant_id: ObjectId | str, area: str, *parts: str) -> str:
    """Dựng khoá từ các đoạn ĐÃ an toàn (mã phiên hex, tên đã qua safe_segment). Một phần được chứa `/` (đường dẫn
    con) — từng đoạn vẫn bị kiểm như thường, sai là KhoaSai chứ không tự sửa."""
    rest = [s for p in parts for s in str(p).split("/")]
    key = "/".join(["tenants", str(tenant_id), area, *rest])
    parse(key, tenant_id)
    return key


def safe_segment(name: object, fallback: str = "file") -> str:
    """Tên tệp bất kỳ → MỘT đoạn khoá hợp lệ (bỏ mọi đường dẫn, giữ nguyên tiếng Việt)."""
    s = str(name or "").replace("\\", "/").split("/")[-1]
    s = _BAD.sub("_", s).strip().rstrip(". ")
    if len(s) > 200:
        stem, ext = os.path.splitext(s)
        s = (stem[: 200 - len(ext)] + ext) if len(ext) <= 20 else s[:200]
        s = s.rstrip(". ")
    if s in ("", ".", ".."):
        return fallback
    return "_" + s if _reserved(s) else s


def safe_parts(rel: object, fallback: str = "file") -> list[str]:
    """Đường dẫn tương đối (vd. `De thi/bai 1.docx`, cả `..\\x`) → các đoạn an toàn; bỏ `.`/`..`/đoạn rỗng."""
    out = [safe_segment(p) for p in str(rel or "").replace("\\", "/").split("/") if p.strip() not in ("", ".", "..")]
    return out or [fallback]
