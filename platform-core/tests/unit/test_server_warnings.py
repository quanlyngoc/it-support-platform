"""core-err.log chỉ được có dòng khi có chuyện thật (Sổ tay 0.7/3.6/3.8): cảnh báo vô hại của gevent bị lọc, cảnh báo
khác vẫn ghi."""
from __future__ import annotations

import warnings

from app.server import _quiet_benign_warnings

LIBUV = "libuv only supports millisecond timer resolution; all times less will be set to 1 ms"


def test_loc_dung_canh_bao_libuv_cua_gevent():
    with warnings.catch_warnings(record=True) as got:
        warnings.simplefilter("always")
        _quiet_benign_warnings()
        warnings.warn_explicit(LIBUV, UserWarning, "timeout.py", 225, module="gevent.timeout")
        warnings.warn_explicit("cảnh báo khác của gevent", UserWarning, "timeout.py", 226, module="gevent.timeout")
        warnings.warn_explicit(LIBUV, UserWarning, "x.py", 1, module="app.khac")  # nơi khác → vẫn ghi
    assert [str(w.message) for w in got] == ["cảnh báo khác của gevent", LIBUV]
