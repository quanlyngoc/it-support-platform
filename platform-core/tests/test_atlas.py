"""Kiểm trên MongoDB Atlas thật (validator $jsonSchema, index unique/TTL). Chạy: uv run pytest -m atlas

Dùng database tạm itm_test_<ngẫu nhiên>, xoá sạch sau khi xong — không đụng itm_core.
"""
from __future__ import annotations

import secrets

import pytest
from pymongo.errors import DuplicateKeyError, WriteError

from app.config.settings import get_settings
from app.db import init as dbinit
from app.tenants import service as tsvc
from app.tenants.repo import ComputerRepo

pytestmark = pytest.mark.atlas


@pytest.fixture(scope="module")
def adb():
    if not _has_env():
        pytest.skip("Không có MONGO_URI")
    from pymongo import MongoClient

    s = get_settings()
    client = MongoClient(s.MONGO_URI, serverSelectionTimeoutMS=15000, tz_aware=True)
    name = f"itm_test_{secrets.token_hex(4)}"
    db = client[name]
    try:
        dbinit.init_database(db)
        yield db
    finally:
        client.drop_database(name)
        client.close()


def _has_env() -> bool:
    try:
        get_settings()
        return True
    except RuntimeError:
        return False


def test_validator_tu_choi_tai_lieu_thieu_tenant(adb):
    with pytest.raises(WriteError):
        adb.computers.insert_one({"hostname": "x"})


def test_khoi_tao_lap_lai_khong_loi(adb):
    dbinit.init_database(adb)  # idempotent
    assert adb.permissions.count_documents({}) >= 14


def test_unique_theo_to_chuc(adb):
    t = tsvc.create_tenant(adb, f"T{secrets.token_hex(3).upper()}", "Thu")
    tsvc.create_user(adb, t["_id"], "u1", password="P@ssw0rd!")
    with pytest.raises(tsvc.TenantError):
        tsvc.create_user(adb, t["_id"], "U1", password="P@ssw0rd!")
    repo = ComputerRepo(adb, t["_id"])
    repo.insert_one({"hostname": "A6-301-01", "agent_id": "ag-1"})
    with pytest.raises(DuplicateKeyError):
        repo.insert_one({"hostname": "A6-301-02", "agent_id": "ag-1"})


def test_bo_ghi_agent_v2_tren_mongodb_that(adb):
    """bulk_upsert + Writer với PyMongo thật (mongomock không phản ánh đúng bulk_write của PyMongo 4.x)."""
    import time

    from app.legacy_adapter.contract import heartbeat
    from app.legacy_adapter.state import LegacyState
    from app.legacy_adapter.writer import Writer
    from app.tenants.repo import repo_for

    t = tsvc.create_tenant(adb, f"V{secrets.token_hex(3).upper()}", "Agent v2")
    clock = [time.time()]
    st = LegacyState(clock=lambda: clock[0])
    w = Writer(adb, t["_id"], st)
    for i in range(1, 31):
        st.ingest(heartbeat(f"A6-301-{i:02d}", f"aa:bb:cc:00:30:{i:02x}", serial=f"SN{i:05d}"), "10.0.0.1")
    assert w.tick() == 30  # 30 máy trong một lượt mạng
    clock[0] += 61
    for i in range(1, 31):
        st.ingest(heartbeat(f"A6-301-{i:02d}", f"aa:bb:cc:00:30:{i:02x}", serial="N/A"), "10.0.0.1")
    w.tick()
    comp = repo_for(adb, t["_id"], "computers")
    doc = comp.find_one({"legacy_hostname": "A6-301-07"})
    assert comp.count({}) == 30 and doc is not None and doc["serial"] == "SN00007"
    assert repo_for(adb, t["_id"], "usage_stats").count({"online_minutes": 1}) == 30
