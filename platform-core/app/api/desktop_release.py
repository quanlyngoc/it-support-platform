"""Phát bản cập nhật Desktop (Sổ tay 4.7) — Tauri updater hỏi `GET /desktop/latest.json` rồi tải bộ cài cùng thư mục.

Tệp nằm ở `<DATA_DIR>/desktop/` (chung mọi tổ chức — Desktop là MỘT phần mềm), do `platform-deployment/desktop/
phat_hanh_desktop.py` chép bộ cài + `.sig` trước rồi ghi `latest.json` SAU CÙNG (bài học phát hành agent hệ cũ: ghi tệp
báo phiên bản cuối cùng để máy khách không thấy bản mới khi bộ cài chưa nằm sẵn).
- Không cần đăng nhập: updater gọi không kèm token. An toàn nhờ chữ ký minisign — ứng dụng chỉ cài bộ cài khớp pubkey
  gắn trong bản đang chạy và số phiên bản nằm trong chữ ký (`requireSignedVersion`).
- Chưa phát hành bản nào → 204: updater hiểu là "không có bản mới", không báo lỗi cho người dùng.
"""
from __future__ import annotations

import re
from pathlib import Path

from apiflask import APIBlueprint, abort
from flask import current_app, send_from_directory

bp = APIBlueprint("desktop_release", __name__, url_prefix="/desktop", tag="Cập nhật Desktop")

_TEN_HOP_LE = re.compile(r"^[A-Za-z0-9._-]+\.(exe|sig)$")  # chỉ bộ cài + chữ ký, tên không dấu cách, không thư mục con


def _dir() -> Path:
    return Path(current_app.config["ITM_SETTINGS"].DATA_DIR) / "desktop"


@bp.get("/latest.json")
@bp.doc(summary="Bản Desktop mới nhất cho Tauri updater (204 khi chưa phát hành bản nào)")
def latest():
    if not (_dir() / "latest.json").is_file():
        return "", 204
    r = send_from_directory(_dir(), "latest.json", mimetype="application/json", max_age=0)
    r.headers["Cache-Control"] = "no-store"
    return r


@bp.get("/<name>")
@bp.doc(summary="Tải bộ cài Desktop / tệp chữ ký")
def download(name: str):
    if not _TEN_HOP_LE.match(name) or not (_dir() / name).is_file():
        abort(404, "Không có tệp này")
    return send_from_directory(_dir(), name, as_attachment=True, max_age=0)
