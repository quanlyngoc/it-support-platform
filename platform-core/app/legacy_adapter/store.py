"""Dữ liệu bất đồng bộ của agent v2 — lưu MongoDB, KHÔNG để RAM (luật A9; bài học hệ cũ §0.3 + 18b).

- `command_results`: phiên (role=session) + kết quả từng máy (role=result) của PowerShell hàng loạt / giao bài /
  thu bài, và kết quả đăng nhập-terminal (role=event). Tự xoá sau 2 ngày (TTL theo created_at).
- `file_metadata` scope=fs_token: token truyền tệp do SERVER cấp (2 giờ, TTL theo expires_at).
- Tệp nằm trên đĩa: <DATA_DIR>/<MÃ TỔ CHỨC>/{work,collect,fs_tmp}/…
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from app.legacy_adapter.identity import norm_host
from app.tenants.repo import repo_for

KINDS = ("ps_bulk", "send", "collect")
FS_TOKEN_TTL = timedelta(hours=2)
CLIP = 20000  # stdout/stderr tối đa (app.py _ps_clip)


def hexid(s: object, n: int = 64) -> str:
    """batch_id / session_id / token luôn là chuỗi hex → lọc sạch để chống path traversal (app.py _safe_id)."""
    return re.sub(r"[^a-fA-F0-9]", "", str(s or ""))[:n].lower()


def safe_name(name: object) -> str:
    """Giữ tên tệp tiếng Việt nhưng bỏ mọi đường dẫn (app.py _safe_name)."""
    s = os.path.basename(str(name or "")).replace("\\", "").replace("/", "").replace("..", "")
    return s.strip()[:200] or "file"


def safe_host(h: object) -> str:
    return (re.sub(r"[^\w\-.]", "_", str(h or "unknown"))[:80]) or "unknown"


def clip(s: object, n: int = CLIP) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[:n] + f"\n...[cắt bớt, tổng {len(s)} ký tự]"


class Store:
    def __init__(self, db: Database, tenant_id: ObjectId, root: Path):
        self.tid = tenant_id
        self.root = root
        self.results = repo_for(db, tenant_id, "command_results")
        self.files = repo_for(db, tenant_id, "file_metadata")

    # ------------------------------------------------------------------ thư mục tệp
    def dir(self, kind: str, *parts: str) -> Path:
        p = self.root.joinpath(kind, *parts)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------------------------ phiên + kết quả
    def create_session(self, kind: str, *, token: str | None = None, meta: dict | None = None) -> str:
        if kind not in KINDS:
            raise ValueError(f"loại phiên lạ: {kind}")
        tok = hexid(token) or uuid.uuid4().hex
        self.results.insert_one({"token": tok, "kind": kind, "role": "session", "meta": meta or {},
                                 "created_at": datetime.now(UTC)})
        return tok

    def session(self, kind: str, token: str) -> dict | None:
        tok = hexid(token)
        if not tok:
            return None
        return self.results.find_one({"token": tok, "kind": kind, "role": "session"})

    def put_result(self, kind: str, token: str, hostname: str, data: dict) -> int:
        """Ghi/ghi đè kết quả của 1 máy trong phiên. Trả số máy đã báo về."""
        tok, host = hexid(token), norm_host(hostname) or "?"
        self.results.update_one({"token": tok, "kind": kind, "role": "result", "hostname": host},
                                {"$set": {**data, "updated_at": datetime.now(UTC)},
                                 "$setOnInsert": {"created_at": datetime.now(UTC)}}, upsert=True)
        return self.results.count({"token": tok, "kind": kind, "role": "result"})

    def put_event(self, kind: str, key: str, data: dict) -> None:
        """Kết quả 1 lần (đăng nhập từ xa / xác thực terminal) — để Desktop poll khi lỡ sự kiện realtime."""
        self.results.insert_one({"token": key, "kind": kind, "role": "event", **data, "created_at": datetime.now(UTC)})

    def read(self, token: str) -> dict | None:
        tok = hexid(token)
        sess = self.results.find_one({"token": tok, "role": "session"}) if tok else None
        if sess is None:
            return None
        rows = list(self.results.find({"token": tok, "kind": sess["kind"], "role": "result"},
                                      {"_id": 0, "tenant_id": 0}))
        return {"token": tok, "kind": sess["kind"], "meta": sess.get("meta", {}),
                "created_at": sess["created_at"].isoformat(), "done": len(rows), "results": rows}

    # ------------------------------------------------------------------ token truyền tệp
    def new_fs_token(self, *, user: str = "", token: str | None = None) -> str:
        tok = hexid(token) or uuid.uuid4().hex
        now = datetime.now(UTC)
        self.files.insert_one({"scope": "fs_token", "token": tok, "user": user, "created_at": now,
                               "expires_at": now + FS_TOKEN_TTL})
        return tok

    def fs_token(self, token: str) -> dict | None:
        tok = hexid(token)
        if not tok:
            return None
        doc = self.files.find_one({"scope": "fs_token", "token": tok})
        if doc is None:
            return None
        exp = doc.get("expires_at")
        if exp is not None and exp.tzinfo is None:  # mongomock/pymongo không tz_aware trả datetime ngây thơ (UTC)
            exp = exp.replace(tzinfo=UTC)
        return doc if exp is None or exp > datetime.now(UTC) else None

    def fs_set(self, token: str, field: str, path: Path) -> None:
        if field not in ("pull_path", "push_path"):
            raise ValueError(field)
        self.files.update_one({"scope": "fs_token", "token": hexid(token)}, {"$set": {field: str(path)}})

    @staticmethod
    def existing(doc: dict | None, field: str) -> Path | None:
        p: Any = (doc or {}).get(field)
        return Path(p) if p and os.path.isfile(p) else None
