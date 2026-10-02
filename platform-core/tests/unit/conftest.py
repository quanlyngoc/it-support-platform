"""Fixture dùng chung cho test bộ tương thích agent v2 và API phòng/thiết bị."""
from __future__ import annotations

import dataclasses
import time

import pytest

from app.server import create_app
from tests.conftest import TEST_SETTINGS, _make_tenant, fake_ldap, login


@pytest.fixture
def world(db, tmp_path):
    """Core có tổ chức PHENIKAA (gắn agent v2) + tổ chức BBB không liên quan; đồng hồ giả điều khiển được."""
    t = {"P": _make_tenant(db, "PHENIKAA"), "B": _make_tenant(db, "BBB")}
    a = create_app(db=db, settings=dataclasses.replace(TEST_SETTINGS, DATA_DIR=str(tmp_path / "data")),
                   async_mode="threading", ldap_bind=fake_ldap)
    ad = a.extensions["legacy"]
    clock = [time.time()]
    ad.state.clock = lambda: clock[0]
    return {"app": a, "ad": ad, "c": a.test_client(), "clock": clock, "tid": t["P"]["tenant"]["_id"], "t": t}


def tok(w, tenant: str = "PHENIKAA", user: str = "admin", pw: str = "Admin@123") -> str:
    code, j = login(w["c"], tenant, user, pw)
    assert code == 200, j
    return j["token"]
