"""Test cho chính công cụ QA (công cụ kiểm hỏng mà báo ĐẠT còn tệ hơn không có công cụ)."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import check_eol  # noqa: E402


def test_check_eol_bat_loi(tmp_path):
    cases = {
        "a.py": (b"x = 1\r\n", "cần LF"),
        "b.bat": (b"@echo off\n", "cần CRLF"),
        "c.ps1": (b"Write-Host 1\r\n", "thiếu BOM"),
        "d.md": (check_eol.BOM + b"# x\n", "không được có BOM"),
    }
    for name, (data, expect) in cases.items():
        p = tmp_path / name
        p.write_bytes(data)
        errs = check_eol.check(p)
        assert errs and expect in errs[0], (name, errs)


def test_check_eol_cho_qua_tep_dung(tmp_path):
    ok = {"a.py": b"x = 1\n", "b.bat": b"@echo off\r\n", "c.ps1": check_eol.BOM + b"Write-Host 1\r\n",
          "e.png": b"\x89PNG\r\n\n"}
    for name, data in ok.items():
        p = tmp_path / name
        p.write_bytes(data)
        assert check_eol.check(p) == [], name


def test_check_eol_quet_that_su_co_tep():
    files = [p for p in check_eol.iter_files(check_eol.ROOT) if p.suffix in check_eol.LF]
    assert len(files) > 30  # nếu bộ lọc thư mục sai, công cụ sẽ "ĐẠT" vì không quét gì
