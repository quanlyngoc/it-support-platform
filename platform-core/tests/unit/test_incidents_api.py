# pyright: reportOptionalSubscript=false
"""API sự cố chỉ đọc (Sổ tay 4.6): số đếm tuyệt đối theo trạng thái + cảnh báo phần cứng, lọc, phạm vi phòng theo
policy, cô lập tổ chức, phải đăng nhập."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bson import ObjectId

from app.rbac.service import create_policy
from app.tenants import service as tsvc
from app.tenants.repo import repo_for
from tests.conftest import auth
from tests.unit.conftest import tok

T0 = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


def _su_co(w, db, tenant="P"):
    r = repo_for(db, w["t"][tenant]["tenant"]["_id"], "incidents")
    rows = [("A6-301-01", "Phòng 301 - A6", "hardware_ram", "PENDING", "MẤT RAM"),
            ("A6-405-01", "Phòng 405 - A6", "cmos", "PROCESSING", "HẾT PIN CMOS"),
            ("A6-301-02", "Phòng 301 - A6", "user", "PENDING", "Máy không lên mạng"),
            ("A6-301-02", "Phòng 301 - A6", "hardware_disk", "DONE", "MẤT Ổ CỨNG")]
    for i, (h, room, cat, st, title) in enumerate(rows if tenant == "P" else rows[:1]):
        r.insert_one({"hostname": h, "room_name": room, "category": cat, "status": st, "title": title,
                      "source": "SYSTEM_WATCHDOG", "created_at": T0 + timedelta(minutes=i)})


def test_dem_va_loc_su_co(world, db):
    _su_co(world, db)
    _su_co(world, db, "B")
    c, t = world["c"], tok(world)
    assert c.get("/api/incidents/summary", headers=auth(t)).get_json() == {
        "open": 3, "pending": 2, "processing": 1, "hardware_open": 2}
    j = c.get("/api/incidents?status=OPEN", headers=auth(t)).get_json()
    assert j["total"] == 3
    assert [i["title"] for i in j["items"]] == ["Máy không lên mạng", "HẾT PIN CMOS", "MẤT RAM"]  # mới nhất trước
    assert "tenant_id" not in j["items"][0] and j["items"][0]["created_at"].startswith("2026-10-03T08:02")
    assert c.get("/api/incidents", headers=auth(t)).get_json()["total"] == 4
    assert c.get("/api/incidents?status=DONE", headers=auth(t)).get_json()["items"][0]["title"] == "MẤT Ổ CỨNG"
    assert c.get("/api/incidents?q=a6-405", headers=auth(t)).get_json()["total"] == 1
    assert c.get("/api/incidents?q=.*", headers=auth(t)).get_json()["total"] == 0  # từ khoá không phải regex
    assert c.get("/api/incidents?status=LUNG_TUNG", headers=auth(t)).status_code == 422
    # đúng tên máy (không phân biệt hoa thường), mọi trạng thái
    assert c.get("/api/incidents?hostname=a6-301-02", headers=auth(t)).get_json()["total"] == 2
    assert c.get("/api/incidents?hostname=A6-301", headers=auth(t)).get_json()["total"] == 0  # không khớp một phần
    rid = str(repo_for(db, world["tid"], "rooms").insert_one({"name": "Phòng 405 - A6"}).inserted_id)
    j = c.get(f"/api/incidents?status=OPEN&room_id={rid}", headers=auth(t)).get_json()
    assert [i["hostname"] for i in j["items"]] == ["A6-405-01"]
    assert c.get("/api/incidents?room_id=khong-phai-id", headers=auth(t)).get_json()["total"] == 0
    # tổ chức BBB chỉ thấy sự cố của mình
    tb = tok(world, tenant="BBB")
    assert c.get("/api/incidents/summary", headers=auth(tb)).get_json()["open"] == 1
    assert c.get("/api/incidents", headers=auth(tb)).get_json()["total"] == 1


def test_pham_vi_phong_va_dang_nhap(world, db):
    _su_co(world, db)
    rid = repo_for(db, world["tid"], "rooms").insert_one({"name": "Phòng 301 - A6"}).inserted_id
    pid = create_policy(db, world["tid"], "Giám thị 301", permission_codes=["user.view"],
                        room_ids=[ObjectId(rid)])["_id"]
    tsvc.create_user(db, world["tid"], "gs301", password="Gs@12345", policy_ids=[pid])
    c, t = world["c"], tok(world, user="gs301", pw="Gs@12345")
    assert c.get("/api/incidents/summary", headers=auth(t)).get_json() == {
        "open": 2, "pending": 2, "processing": 0, "hardware_open": 1}
    assert {i["hostname"] for i in c.get("/api/incidents", headers=auth(t)).get_json()["items"]} == {
        "A6-301-01", "A6-301-02"}
    id405 = str(repo_for(db, world["tid"], "rooms").insert_one({"name": "Phòng 405 - A6"}).inserted_id)
    assert c.get(f"/api/incidents?room_id={id405}", headers=auth(t)).get_json()["total"] == 0  # ngoài phạm vi
    assert c.get(f"/api/incidents?room_id={rid}", headers=auth(t)).get_json()["total"] == 3
    assert c.get("/api/incidents").status_code == 401
    assert c.get("/api/incidents/summary").status_code == 401
