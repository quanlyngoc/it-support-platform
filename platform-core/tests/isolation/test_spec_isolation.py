# pyright: reportOptionalSubscript=false
"""Đối chiếu 1-1 với danh sách test bắt buộc của đặc tả: §4A.36 (15 mục) và §77 (8 mục).

Mục nào cần module chưa xây (tệp, lệnh agent, báo cáo...) thì kiểm ở tầng repository ngay bây giờ, và có thêm một
test mức API đang `skip` ghi rõ giai đoạn sẽ làm — để luôn hiện trong kết quả pytest, không bị quên.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.rbac.catalog import UnknownPermission, validate_permission_ids
from app.rbac.service import create_policy
from app.tenants import service as tsvc
from app.tenants.refs import RefNotFound, require_refs
from app.tenants.repo import repo_for
from tests.conftest import auth, login


def _r(db, tid, col):
    return repo_for(db, tid, col)


@pytest.fixture
def world(db, two_tenants):
    """Mỗi tổ chức: 1 phòng, 1 máy, 1 agent, 1 sự cố, 1 tin chat, 1 tệp, 1 usage, 1 dòng audit."""
    out = {}
    for k, t in two_tenants.items():
        tid = t["tenant"]["_id"]
        room = _r(db, tid, "rooms").insert_one({"name": f"Phòng 301 - {k}"}).inserted_id
        dev = _r(db, tid, "computers").insert_one({"hostname": f"{k}-301-01", "mac": "AA:BB", "room_id": room,
                                                   "agent_id": f"ag-{k}"}).inserted_id
        agent = _r(db, tid, "agents").insert_one({"agent_id": f"ag-{k}", "device_id": dev}).inserted_id
        inc = _r(db, tid, "incidents").insert_one({"device_id": dev, "room_id": room, "status": "OPEN",
                                                   "title": f"Hỏng chuột {k}"}).inserted_id
        msg = _r(db, tid, "chat_messages").insert_one({"scope": "LAB", "room_id": room, "text": f"chào {k}"}
                                                      ).inserted_id
        f = _r(db, tid, "file_metadata").insert_one({"scope": "work", "storage_key": f"tenants/{tid}/work/x"}
                                                    ).inserted_id
        _r(db, tid, "usage_stats").insert_one({"device_id": dev, "date": "2026-10-02", "minutes": 60})
        _r(db, tid, "audit_log").insert_one({"action": f"TEST {k}", "created_at": datetime.now(UTC)})
        out[k] = {"tid": tid, "room": room, "dev": dev, "agent": agent, "inc": inc, "msg": msg, "file": f}
    return out


def _cross_get(db, world, col, key):
    a, b = world["A"], world["B"]
    assert _r(db, a["tid"], col).get(a[key]) is not None
    return _r(db, a["tid"], col).get(b[key])


# ===================== §4A.36 =====================
def test_4a36_01_khong_doc_device_cua_to_chuc_khac(db, world):
    assert _cross_get(db, world, "computers", "dev") is None


def test_4a36_02_khong_sua_device_cua_to_chuc_khac(db, world):
    a, b = world["A"], world["B"]
    assert _r(db, a["tid"], "computers").update_by_id(b["dev"], {"$set": {"hostname": "x"}}).matched_count == 0
    assert _r(db, b["tid"], "computers").get(b["dev"])["hostname"] == "B-301-01"


def test_4a36_03_khong_doc_incident_cua_to_chuc_khac(db, world):
    assert _cross_get(db, world, "incidents", "inc") is None


def test_4a36_04_khong_doc_chat_cua_to_chuc_khac(db, world):
    assert _cross_get(db, world, "chat_messages", "msg") is None
    assert [m["text"] for m in _r(db, world["A"]["tid"], "chat_messages").find()] == ["chào A"]


def test_4a36_05_khong_lay_metadata_tep_cua_to_chuc_khac(db, world):
    assert _cross_get(db, world, "file_metadata", "file") is None


@pytest.mark.skip(reason="GĐ7: API tải tệp /api/files/<id> — kiểm token tổ chức A không tải được tệp B")
def test_4a36_05b_api_download_tep_cheo_to_chuc():
    pass


def test_4a36_06_user_khong_dung_duoc_phien_cua_to_chuc_khac(client, world):
    _, ja = login(client, "AAA", "gv01", "Gv@12345")
    me = client.get("/api/auth/me", headers={**auth(ja["token"]), "X-Tenant-Code": "BBB"}).get_json()
    assert me["tenant_code"] == "AAA"  # tổ chức lấy từ phiên; header/tham số do client gửi bị bỏ qua


def test_4a36_07_agent_khong_thay_ket_qua_lenh_cua_to_chuc_khac(db, world):
    a, b = world["A"], world["B"]
    _r(db, b["tid"], "command_results").insert_one({"token": "tok-b", "host": "B-301-01", "out": "bi mat"})
    assert _r(db, a["tid"], "command_results").find_one({"token": "tok-b"}) is None


@pytest.mark.skip(reason="GĐ3/GĐ10: dispatch lệnh qua socket room t:<tenant>:host:<host> — agent A không nhận lệnh B")
def test_4a36_07b_agent_khong_nhan_lenh_qua_socket():
    pass


def test_4a36_08_device_khong_gan_duoc_room_cua_to_chuc_khac(db, world):
    a, b = world["A"], world["B"]
    with pytest.raises(RefNotFound):
        require_refs(db, a["tid"], rooms=b["room"])
    require_refs(db, a["tid"], rooms=a["room"])  # cùng tổ chức thì qua


def test_4a36_09_agent_khong_gan_duoc_device_cua_to_chuc_khac(db, world):
    a, b = world["A"], world["B"]
    with pytest.raises(RefNotFound):
        require_refs(db, a["tid"], computers=b["dev"])
    with pytest.raises(RefNotFound):
        require_refs(db, a["tid"], computers=[a["dev"], b["dev"]])  # lẫn 1 id ngoài tổ chức cũng bị chặn


def test_4a36_10_bao_cao_chi_chua_du_lieu_trong_to_chuc(db, world):
    a = world["A"]
    rows = list(_r(db, a["tid"], "usage_stats").aggregate([{"$group": {"_id": None, "m": {"$sum": "$minutes"}}}]))
    assert rows[0]["m"] == 60  # không cộng 60 phút của B


def test_4a36_11_mac_trong_to_chuc_khong_unique_theo_v3(db, world):
    # Đặc tả V2 ghi "Unique MAC"; V3 sửa: MAC KHÔNG unique (tráo phần cứng 16/09 làm mất 5 máy). Định danh = agent_id.
    a, b = world["A"], world["B"]
    _r(db, a["tid"], "computers").insert_one({"hostname": "A-301-02", "mac": "AA:BB", "agent_id": "ag-A2"})
    with pytest.raises(DuplicateKeyError):
        _r(db, a["tid"], "computers").insert_one({"hostname": "A-301-03", "agent_id": "ag-A"})
    _r(db, b["tid"], "computers").insert_one({"hostname": "B-301-09", "agent_id": "ag-A"})  # khác tổ chức thì được


def test_4a36_12_catalog_quyen_khong_trung(db):
    codes = [p["code"] for p in db.permissions.find()]
    assert len(codes) == len(set(codes)) >= 14
    with pytest.raises(DuplicateKeyError):
        db.permissions.insert_one({"code": "device.control", "name": "trùng"})


def test_4a36_13_policy_khong_tham_chieu_quyen_khong_ton_tai(db, world):
    tid = world["A"]["tid"]
    with pytest.raises(UnknownPermission):
        create_policy(db, tid, "Sai", permission_codes=["khong.co"])
    with pytest.raises(UnknownPermission):
        validate_permission_ids(db, [ObjectId()])
    with pytest.raises(RefNotFound):
        create_policy(db, tid, "Phòng lạ", permission_codes=["device.control"], room_ids=[world["B"]["room"]])
    p = create_policy(db, tid, "Đúng", permission_codes=["device.control"], room_ids=[world["A"]["room"]])
    assert p["room_ids"] == [world["A"]["room"]]


def test_4a36_14_reaction_khong_trung(db, world):
    a = world["A"]
    r = _r(db, a["tid"], "chat_reactions")
    uid = ObjectId()
    r.insert_one({"message_id": a["msg"], "user_id": uid, "reaction": "👍"})
    with pytest.raises(DuplicateKeyError):
        r.insert_one({"message_id": a["msg"], "user_id": uid, "reaction": "👍"})
    r.insert_one({"message_id": a["msg"], "user_id": uid, "reaction": "❤️"})


def test_4a36_15_usage_stats_khong_trung_theo_to_chuc_may_ngay(db, world):
    a, b = world["A"], world["B"]
    with pytest.raises(DuplicateKeyError):
        _r(db, a["tid"], "usage_stats").insert_one({"device_id": a["dev"], "date": "2026-10-02", "minutes": 1})
    _r(db, b["tid"], "usage_stats").insert_one({"device_id": a["dev"], "date": "2026-10-02", "minutes": 1})


# ===================== §77 =====================
def test_77_1_user_a_khong_doc_device_b(db, world):
    assert _cross_get(db, world, "computers", "dev") is None


def test_77_2_user_a_khong_doc_incident_b(db, world):
    assert _cross_get(db, world, "incidents", "inc") is None


def test_77_3_user_a_khong_doc_chat_b(db, world):
    assert _cross_get(db, world, "chat_messages", "msg") is None


def test_77_4_agent_a_khong_nhan_command_b(db, world):
    test_4a36_07_agent_khong_thay_ket_qua_lenh_cua_to_chuc_khac(db, world)


def test_77_5_tep_a_khong_lay_duoc_bang_to_chuc_b(db, world):
    a, b = world["A"], world["B"]
    assert _r(db, b["tid"], "file_metadata").get(a["file"]) is None


def test_77_6_phong_a_khong_truy_cap_bang_user_b(db, world):
    a, b = world["A"], world["B"]
    assert _r(db, b["tid"], "rooms").get(a["room"]) is None
    with pytest.raises(RefNotFound):
        tsvc.create_user(db, b["tid"], "gv-lan", password="x1234567", policy_ids=[
            _r(db, a["tid"], "policies").find_one({"name": "Chi xem"})["_id"]])  # policy của A không gán cho user B


def test_77_7_bao_cao_a_khong_chua_du_lieu_b(db, world):
    test_4a36_10_bao_cao_chi_chua_du_lieu_trong_to_chuc(db, world)


def test_77_8_audit_a_khong_hien_du_lieu_b(db, world):
    actions = [r["action"] for r in _r(db, world["A"]["tid"], "audit_log").find()]
    assert "TEST A" in actions and "TEST B" not in actions
