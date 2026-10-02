"""Kiểm line ending + BOM toàn repo theo CLAUDE.md §2 (bài học hệ cũ: sai line ending là hỏng .bat/Nuitka/PowerShell).

    uv run --project platform-core python platform-deployment/qa/check_eol.py
Thoát mã 0 = đạt.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "target", "__pycache__", ".pytest_cache", ".ruff_cache",
             "logs", ".mypy_cache"}
LF = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".toml", ".md", ".yml", ".yaml", ".html", ".css", ".txt",
      ".lock", ".cfg", ".ini", ".rs"}
CRLF = {".bat", ".cmd", ".iss", ".ps1"}
NEED_BOM = {".ps1"}  # PowerShell 5.1 đọc UTF-8 không BOM thành ANSI -> vỡ tiếng Việt
NO_BOM = LF | {".bat", ".cmd", ".iss"}
BOM = b"\xef\xbb\xbf"


def check(path: pathlib.Path) -> list[str]:
    ext = path.suffix.lower()
    if ext not in LF | CRLF:
        return []
    data = path.read_bytes()
    errs = []
    crlf = data.count(b"\r\n")
    lone_lf = data.count(b"\n") - crlf
    if ext in CRLF and lone_lf:
        errs.append(f"cần CRLF nhưng có {lone_lf} dòng LF")
    if ext in LF and crlf:
        errs.append(f"cần LF nhưng có {crlf} dòng CRLF")
    if ext in NEED_BOM and not data.startswith(BOM) and data:
        errs.append("thiếu BOM UTF-8")
    if ext in NO_BOM and data.startswith(BOM):
        errs.append("không được có BOM")
    return errs


def iter_files(root: pathlib.Path):
    for p in root.rglob("*"):
        if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS):
            yield p


def main() -> int:
    bad = 0
    for p in iter_files(ROOT):
        for e in check(p):
            print(f"[EOL] {p.relative_to(ROOT)}: {e}")
            bad += 1
    print("check_eol:", "ĐẠT" if not bad else f"{bad} lỗi")
    return 1 if bad else 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        getattr(s, "reconfigure", lambda **_: None)(encoding="utf-8", errors="replace")
    raise SystemExit(main())
