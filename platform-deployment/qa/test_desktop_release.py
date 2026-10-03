"""Test script phát hành Desktop (Sổ tay 4.7) trên bộ cài + chữ ký giả: thứ tự ghi, kiểm phiên bản trong chữ ký,
tên không dấu cách, giữ 3 bản gần nhất."""
from __future__ import annotations

import base64
import json
import pathlib
import sys
from datetime import UTC, datetime

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "desktop"))

import phat_hanh_desktop as ph  # noqa: E402


def _sig(version: str | None) -> str:
    tc = "timestamp:1759480000\tfile:Phenikaa IT Monitor_x64-setup.exe" + (f"\tversion:{version}" if version else "")
    raw = f"untrusted comment: signature from tauri secret key\nRUQ...\ntrusted comment: {tc}\nAAAA\n"
    return base64.b64encode(raw.encode()).decode()


def _build(tmp: pathlib.Path, version: str, sig_version: str | None) -> tuple[pathlib.Path, pathlib.Path]:
    conf = tmp / "tauri.conf.json"
    conf.write_text(json.dumps({"productName": "Phenikaa IT Monitor", "version": version}), encoding="utf-8")
    bundle = tmp / "nsis"
    bundle.mkdir(exist_ok=True)
    exe = bundle / f"Phenikaa IT Monitor_{version}_x64-setup.exe"
    exe.write_bytes(b"MZ" + version.encode())
    (bundle / (exe.name + ".sig")).write_text(_sig(sig_version), encoding="utf-8")
    return conf, bundle


def test_phat_hanh_ghi_dung_va_latest_cuoi_cung(tmp_path):
    conf, bundle = _build(tmp_path, "0.1.1", "0.1.1")
    data = tmp_path / "data"
    r = ph.phat_hanh(data_dir=data, base_url="https://10.21.24.142:7443/", notes="Thử", conf=conf, bundle=bundle,
                     now=datetime(2026, 10, 3, 1, 2, 3, tzinfo=UTC))
    out = data / "desktop"
    assert r["file"] == "Phenikaa-IT-Monitor_0.1.1_x64-setup.exe" and r["removed"] == []
    assert (out / r["file"]).read_bytes() == b"MZ0.1.1"
    j = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert j["version"] == "0.1.1" and j["notes"] == "Thử" and j["pub_date"] == "2026-10-03T01:02:03Z"
    p = j["platforms"]["windows-x86_64"]
    assert p["url"] == "https://10.21.24.142:7443/desktop/Phenikaa-IT-Monitor_0.1.1_x64-setup.exe"
    assert p["signature"] == (out / (r["file"] + ".sig")).read_text(encoding="utf-8")
    assert not list(out.glob("*.tmp"))


def test_chu_ky_lech_phien_ban_hoac_hong_thi_dung(tmp_path):
    conf, bundle = _build(tmp_path, "0.1.2", "0.1.1")
    with pytest.raises(SystemExit, match="0.1.1"):
        ph.phat_hanh(data_dir=tmp_path / "d", base_url="https://x", notes="", conf=conf, bundle=bundle)
    assert not (tmp_path / "d" / "desktop" / "latest.json").exists()  # dừng TRƯỚC khi chép/ghi gì
    (bundle / "Phenikaa IT Monitor_0.1.2_x64-setup.exe.sig").write_text("khong-phai-base64!", encoding="utf-8")
    with pytest.raises(SystemExit, match="không đọc được"):
        ph.phat_hanh(data_dir=tmp_path / "d", base_url="https://x", notes="", conf=conf, bundle=bundle)
    (tmp_path / "k").mkdir()
    conf2, bundle2 = _build(tmp_path / "k", "0.1.3", None)
    r = ph.phat_hanh(data_dir=tmp_path / "d", base_url="https://x", notes="", conf=conf2, bundle=bundle2)
    assert r["version"] == "0.1.3"  # chữ ký kiểu cũ (không ghi version) vẫn nhận


def test_thieu_bo_cai_va_giu_3_ban(tmp_path):
    conf, bundle = _build(tmp_path, "0.1.0", "0.1.0")
    (bundle / "Phenikaa IT Monitor_0.1.0_x64-setup.exe").unlink()
    with pytest.raises(SystemExit, match="Không thấy bộ cài"):
        ph.phat_hanh(data_dir=tmp_path / "d", base_url="https://x", notes="", conf=conf, bundle=bundle)
    for v in ("0.1.9", "0.1.10", "0.2.0", "0.1.8"):
        c, b = _build(tmp_path, v, v)
        ph.phat_hanh(data_dir=tmp_path / "d", base_url="https://x", notes="", conf=c, bundle=b)
    con = sorted(p.name for p in (tmp_path / "d" / "desktop").glob("*.exe"))
    # 0.1.8 phát hành sau cùng (hạ cấp) → latest.json trỏ tới nó nên PHẢI giữ; còn lại giữ 2 bản số lớn nhất (so
    # theo số, không theo chữ: 0.1.10 > 0.1.9)
    assert con == ["Phenikaa-IT-Monitor_0.1.10_x64-setup.exe", "Phenikaa-IT-Monitor_0.1.8_x64-setup.exe",
                   "Phenikaa-IT-Monitor_0.2.0_x64-setup.exe"]
    latest = json.loads((tmp_path / "d" / "desktop" / "latest.json").read_text(encoding="utf-8"))
    assert latest["platforms"]["windows-x86_64"]["url"].endswith("_0.1.8_x64-setup.exe")


def test_main_doc_ghi_chu_co_dau_tu_tep(tmp_path, capsys):
    conf, bundle = _build(tmp_path, "0.2.1", "0.2.1")
    gc = tmp_path / "ghi_chu.txt"
    gc.write_text("﻿Sửa lỗi đồng hồ\n", encoding="utf-8")  # có BOM (Notepad) vẫn đọc đúng
    rc = ph.main(["--data-dir", str(tmp_path / "d"), "--base-url", "https://x", "--notes-file", str(gc),
                  "--conf", str(conf), "--bundle", str(bundle)])
    assert rc == 0 and "PHÁT HÀNH OK: 0.2.1" in capsys.readouterr().out
    latest = json.loads((tmp_path / "d" / "desktop" / "latest.json").read_text(encoding="utf-8"))
    assert latest["notes"] == "Sửa lỗi đồng hồ"
    with pytest.raises(SystemExit):  # --notes và --notes-file không đi cùng nhau
        ph.main(["--data-dir", "x", "--base-url", "y", "--notes", "a", "--notes-file", str(gc)])
