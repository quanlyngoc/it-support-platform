# pyright: reportOptionalSubscript=false
"""Cô lập tổ chức ở tầng repository (đặc tả 4A.3, 4A.36, 49.2, quy tắc AI 1–5)."""
from __future__ import annotations

import pytest
from bson import ObjectId

from app.tenants.repo import ComputerRepo, TenantRepo, TenantScopeError, UserRepo


def _seed_computers(db, two):
    a, b = two["A"]["tenant"]["_id"], two["B"]["tenant"]["_id"]
    ia = ComputerRepo(db, a).insert_one({"hostname": "A6-301-01", "mac": "aa"}).inserted_id
    ib = ComputerRepo(db, b).insert_one({"hostname": "B-101-01", "mac": "aa"}).inserted_id
    return a, b, ia, ib


def test_khong_doc_duoc_may_cua_to_chuc_khac(db, two_tenants):
    a, b, ia, ib = _seed_computers(db, two_tenants)
    ra = ComputerRepo(db, a)
    assert ra.get(ia)["hostname"] == "A6-301-01"
    assert ra.get(ib) is None
    assert [d["hostname"] for d in ra.find()] == ["A6-301-01"]
    assert ra.count() == 1


def test_khong_sua_khong_xoa_duoc_may_cua_to_chuc_khac(db, two_tenants):
    a, b, ia, ib = _seed_computers(db, two_tenants)
    ra = ComputerRepo(db, a)
    assert ra.update_by_id(ib, {"$set": {"hostname": "HACK"}}).matched_count == 0
    assert ra.delete_by_id(ib).deleted_count == 0
    assert ComputerRepo(db, b).get(ib)["hostname"] == "B-101-01"


def test_truy_van_hoac_ghi_mang_tenant_khac_bi_tu_choi(db, two_tenants):
    a, b, _, _ = _seed_computers(db, two_tenants)
    ra = ComputerRepo(db, a)
    with pytest.raises(TenantScopeError):
        list(ra.find({"tenant_id": b}))
    with pytest.raises(TenantScopeError):
        ra.insert_one({"hostname": "x", "tenant_id": b})
    with pytest.raises(TenantScopeError):
        ra.update_one({"hostname": "A6-301-01"}, {"$set": {"tenant_id": b}})
    with pytest.raises(TenantScopeError):
        ra.update_one({"hostname": "A6-301-01"}, {"$setOnInsert": {"tenant_id": b}}, upsert=True)
    with pytest.raises(TenantScopeError):
        ra.delete_many({})


def test_upsert_va_insert_luon_gan_dung_to_chuc(db, two_tenants):
    a, _, _, _ = _seed_computers(db, two_tenants)
    ra = ComputerRepo(db, a)
    ra.update_one({"hostname": "A6-301-99"}, {"$set": {"mac": "bb"}}, upsert=True)
    assert db["computers"].find_one({"hostname": "A6-301-99"})["tenant_id"] == a


def test_aggregate_chi_trong_to_chuc_va_cam_lookup(db, two_tenants):
    a, _, _, _ = _seed_computers(db, two_tenants)
    ra = ComputerRepo(db, a)
    rows = list(ra.aggregate([{"$group": {"_id": "$mac", "n": {"$sum": 1}}}]))
    assert rows == [{"_id": "aa", "n": 1}]
    with pytest.raises(TenantScopeError):
        list(ra.aggregate([{"$lookup": {"from": "users", "localField": "x", "foreignField": "y", "as": "z"}}]))


def test_repo_tu_choi_tenant_khong_hop_le_va_collection_platform():
    class Bad(TenantRepo):
        collection = "tenants"

    with pytest.raises(TenantScopeError):
        UserRepo(None, "AAA")  # type: ignore[arg-type]
    with pytest.raises(TenantScopeError):
        Bad(None, ObjectId())  # type: ignore[arg-type]


def test_trung_ten_dang_nhap_o_hai_to_chuc_khac_nhau_van_hop_le(db, two_tenants):
    # Cả A và B đều có "admin" — unique theo (tenant_id, username_lc)
    assert UserRepo(db, two_tenants["A"]["tenant"]["_id"]).find_one({"username_lc": "admin"})
    assert UserRepo(db, two_tenants["B"]["tenant"]["_id"]).find_one({"username_lc": "admin"})
