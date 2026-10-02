"""Ép stdout/stderr sang UTF-8: console Windows (cp1252) và log NSSM làm print tiếng Việt nổ UnicodeEncodeError."""
from __future__ import annotations

import sys


def utf8_stdio() -> None:
    for s in (sys.stdout, sys.stderr):
        reconfigure = getattr(s, "reconfigure", None)  # thiếu khi stdout bị thay bằng đối tượng khác (test, NSSM)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except ValueError:
                pass
