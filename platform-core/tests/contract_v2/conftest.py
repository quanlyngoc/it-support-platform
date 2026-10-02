"""Test hợp đồng chạy trên app có sẵn tổ chức PHENIKAA — tổ chức mà giao thức v2 gắn vào (LEGACY_TENANT_CODE)."""
from __future__ import annotations

import pytest

from app.tenants import service as tsvc


@pytest.fixture
def app(app, db):  # mở rộng fixture `app` gốc
    tsvc.create_tenant(db, app.extensions["legacy"].s.LEGACY_TENANT_CODE, "Phenikaa")
    return app
