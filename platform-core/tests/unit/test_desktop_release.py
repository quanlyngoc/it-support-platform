"""Kho phát hành Desktop `/desktop/*` (Sổ tay 4.7): chưa phát hành → 204 (updater hiểu "không có bản mới"),
latest.json không cache, chỉ tải được bộ cài/chữ ký đúng mẫu tên, không thoát ra ngoài thư mục."""
from __future__ import annotations

import json
from pathlib import Path


def _kho(app) -> Path:
    d = Path(app.config["ITM_SETTINGS"].DATA_DIR) / "desktop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_chua_phat_hanh_tra_204(client):
    r = client.get("/desktop/latest.json")
    assert r.status_code == 204 and r.data == b""


def test_latest_va_tai_bo_cai(app, client):
    kho = _kho(app)
    (kho / "latest.json").write_text(json.dumps({"version": "0.1.1"}), encoding="utf-8")
    (kho / "Phenikaa-IT-Monitor_0.1.1_x64-setup.exe").write_bytes(b"MZ-bo-cai")
    (kho / "Phenikaa-IT-Monitor_0.1.1_x64-setup.exe.sig").write_text("c2ln", encoding="utf-8")
    (kho / "bi-mat.txt").write_text("x", encoding="utf-8")
    r = client.get("/desktop/latest.json")
    assert r.status_code == 200 and r.get_json() == {"version": "0.1.1"}
    assert r.headers["Cache-Control"] == "no-store"
    r = client.get("/desktop/Phenikaa-IT-Monitor_0.1.1_x64-setup.exe")
    assert r.status_code == 200 and r.data == b"MZ-bo-cai"
    assert client.get("/desktop/Phenikaa-IT-Monitor_0.1.1_x64-setup.exe.sig").data == b"c2ln"
    assert client.get("/desktop/bi-mat.txt").status_code == 404  # chỉ .exe / .sig
    assert client.get("/desktop/khong-co_0.9_x64-setup.exe").status_code == 404
    assert client.get("/desktop/..%5Clatest.json").status_code == 404
