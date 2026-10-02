"""Fixture dùng chung. Mặc định chạy trên mongomock (nhanh, không cần mạng); test `atlas` chạy trên CSDL thật."""
from __future__ import annotations

import mongomock
import pytest
from apiflask import APIBlueprint

from app.auth import service as auth_service
from app.config.settings import Settings
from app.db import seeds
from app.db.indexes import INDEXES
from app.rbac.perms import require_perm
from app.rbac.service import create_policy
from app.server import create_app
from app.tenants import service as tsvc

TEST_SETTINGS = Settings(MONGO_URI="mongodb://khong-dung", MONGO_DB="itm_test")
AD_PASSWORD = "ad-pass-dung"


def fake_ldap(cfg: dict, principal: str, password: str) -> bool:
    return password == AD_PASSWORD


@pytest.fixture
def db():
    d = mongomock.MongoClient()["itm_test"]
    for col, specs in INDEXES.items():  # cùng bộ index với CSDL thật (mongomock bỏ qua TTL)
        for keys, opts in specs:
            d[col].create_index(keys, **opts)
    seeds.seed(d)
    auth_service.clear_cache()
    yield d
    auth_service.clear_cache()


def _make_tenant(db, code: str) -> dict:
    t = tsvc.create_tenant(db, code, f"To chuc {code}")
    super_pid = tsvc.super_admin_policy_id(db, t["_id"])
    view_pid = create_policy(db, t["_id"], "Chi xem", permission_codes=["user.view"])["_id"]
    admin = tsvc.create_user(db, t["_id"], "admin", password="Admin@123", policy_ids=[super_pid])
    staff = tsvc.create_user(db, t["_id"], "gv01", password="Gv@12345", policy_ids=[view_pid])
    return {"tenant": t, "admin": admin, "staff": staff, "super_pid": super_pid, "view_pid": view_pid}


@pytest.fixture
def two_tenants(db):
    return {"A": _make_tenant(db, "AAA"), "B": _make_tenant(db, "BBB")}


@pytest.fixture
def app(db):
    a = create_app(db=db, settings=TEST_SETTINGS, async_mode="threading", ldap_bind=fake_ldap)
    a.config["TESTING"] = True

    # Route thử nghiệm để kiểm quyền + nhật ký (chỉ có trong test)
    tbp = APIBlueprint("test_only", __name__, url_prefix="/api/test")

    @tbp.post("/control")
    @require_perm("device.control")
    def control():
        return {"ok": True}

    a.register_blueprint(tbp)
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, tenant: str, username: str, password: str, *, ip: str | None = None, xff: str | None = None,
          **body) -> tuple[int, dict]:
    """Gọi /api/auth/login. `ip` giả lập địa chỉ kết nối, `xff` giả lập header X-Forwarded-For của Caddy."""
    extra: dict = {}
    if ip:
        extra["environ_base"] = {"REMOTE_ADDR": ip}
    if xff:
        extra["headers"] = {"X-Forwarded-For": xff}
    r = client.post("/api/auth/login",
                    json={"tenant_code": tenant, "username": username, "password": password, **body}, **extra)
    return r.status_code, r.get_json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
