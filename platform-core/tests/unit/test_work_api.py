# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Sổ tay 7.3: giao bài / thu bài / nhật ký — agent v2 không đổi; sổ `pushed_files` chỉ ghi tệp agent BÁO đã ghi; xoá
tệp đã giao xếp hàng khi máy tắt; thu bài đủ trạng thái ok/nofile/nofolder/fail/offline; tải từng máy / tất cả / từng
tệp; lưu cấu trúc THU; chốt an toàn đường dẫn máy trạm; phạm vi phòng."""
from __future__ import annotations

import io
import zipfile
from urllib.parse import quote

from bson import ObjectId

from app.legacy_adapter import contract as k
from app.rbac.service import create_policy
from app.tenants import service as tsvc
from app.tenants.repo import repo_for
from app.work import service as svc
from tests.conftest import auth
from tests.unit.conftest import tok
from tests.unit.test_power_api import MAY, _dung


def _len(world, host):
    """Đưa máy lên lại (nhịp tim + socket)."""
    ag = k.agent(world["app"], host, MAY[host][0])
    world["ad"].state.ingest(k.heartbeat(host, MAY[host][0], ip=MAY[host][1]), "127.0.0.1")
    ag.get_received()
    return ag


def _lo(c, t, files: dict[str, bytes]) -> str:
    bid = ""
    for name, body in files.items():
        q = f"?name={quote(name)}" + (f"&batch={bid}" if bid else "")
        j = c.post(f"/api/work/upload{q}", data=body, headers=auth(t)).get_json()
        bid = j["batch_id"]
    return bid


def _cmd(ag, action):
    return [e["command_obj"] for e in k.got(ag, "execute_command")
            if (e.get("command_obj") or {}).get("action") == action]


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


# ====================================================================== GIAO BÀI
def test_giao_bai_ghi_so_dung_tep_agent_bao_da_ghi(world, db):
    ag, _, rooms = _dung(world)
    ag["A6-301-02"] = _len(world, "A6-301-02")
    c, t = world["c"], tok(world)
    bid = _lo(c, t, {"DeThi/Phan1/bai.mp3": b"MP3", "De<1>.docx": b"DOCX"})
    assert c.get(f"/api/work/batches/{bid}", headers=auth(t)).get_json()["files"] == [
        {"name": "De1.docx", "size": 4}, {"name": "DeThi/Phan1/bai.mp3", "size": 3}]
    r = c.post("/api/work/send", json={"batch_id": bid, "room_ids": [rooms["Phòng 301 - A6"]],
                                       "dest_folder": r"C:\BaiTap", "overwrite": False}, headers=auth(t))
    j = r.get_json()
    assert r.status_code == 200 and j["total"] == 2 and j["dest_dir"] == r"C:\BaiTap"
    assert {s["hostname"]: s["reason"] for s in j["skipped"]} == {"A6-301-GV": "máy giảng viên"}
    co = _cmd(ag["A6-301-01"], "receive_work")[0]
    assert co == {"action": "receive_work", "batch_id": bid, "files": ["De1.docx", "DeThi/Phan1/bai.mp3"],
                  "dest_folder": r"C:\BaiTap", "overwrite": False, "session_id": j["session_id"],
                  "report_url": "/send_report"}
    assert not _cmd(ag["A6-301-GV"], "receive_work")
    # Agent tải đúng tên Core gửi (quote như client.py) — kho chung, không qua RAM
    assert c.get(f"/work_file/{bid}/{quote('DeThi/Phan1/bai.mp3')}").data == b"MP3"
    st = c.get(f"/api/work/send/{j['session_id']}", headers=auth(t)).get_json()
    assert st["complete"] is False and {r["status"] for r in st["results"]} == {"running"}
    # 01 ghi được 1 tệp, tệp kia "đã có, bỏ qua" (KHÔNG phải của mình → không được ghi sổ để xoá); 02 hỏng ổ
    c.post("/send_report", json={"session_id": j["session_id"], "hostname": "A6-301-01", "status": "ok", "saved": 1,
                                 "skipped": 1, "failed": 0, "files": [
                                     {"name": "De1.docx", "ok": True, "note": "đã có, bỏ qua"},
                                     {"name": "DeThi/Phan1/bai.mp3", "ok": True}]})
    c.post("/send_report", json={"session_id": j["session_id"], "hostname": "A6-301-02", "status": "fail",
                                 "failed": 2, "reason": "Ổ đĩa đầy", "files": [
                                     {"name": "De1.docx", "ok": False, "error": "Ổ đĩa đầy"}]})
    st = c.get(f"/api/work/send/{j['session_id']}", headers=auth(t)).get_json()
    assert st["complete"] is True and [(r["hostname"], r["status"], r["saved"]) for r in st["results"]] == [
        ("A6-301-01", "ok", 1), ("A6-301-02", "fail", 0)]
    so = list(repo_for(db, world["tid"], "pushed_files").find({}, {"_id": 0, "hostname": 1, "full_path": 1}))
    assert so == [{"hostname": "A6-301-01", "full_path": r"C:\BaiTap\DeThi\Phan1\bai.mp3"}]
    items = c.get("/api/work/pushed", headers=auth(t)).get_json()["items"]
    assert [(i["hostname"], i["folder"], i["filename"], i["status"], i["online"]) for i in items] == [
        ("A6-301-01", r"C:\BaiTap\DeThi\Phan1", r"DeThi\Phan1\bai.mp3", "pushed", True)]


def test_xoa_tep_da_giao_xep_hang_khi_may_tat(world, db):
    ag, _, rooms = _dung(world)
    ag2 = _len(world, "A6-301-02")
    c, t = world["c"], tok(world)
    bid = _lo(c, t, {"a.docx": b"A"})
    sid = c.post("/api/work/send", json={"batch_id": bid, "room_ids": [rooms["Phòng 301 - A6"]]},
                 headers=auth(t)).get_json()["session_id"]
    for h in ("A6-301-01", "A6-301-02"):
        c.post("/send_report", json={"session_id": sid, "hostname": h, "status": "ok", "saved": 1,
                                     "files": [{"name": "a.docx", "ok": True}]})
    ag2.disconnect()  # 02 tắt trước khi xoá
    ag["A6-301-01"].get_received()
    j = c.post("/api/work/pushed/delete", json={}, headers=auth(t)).get_json()
    assert (j["deleted"], j["kept"], j["machines"]) == (1, 1, 1) and "TỰ ĐỘNG" in j["message"]
    fs = k.got(ag["A6-301-01"], "fs_request")
    assert [(x["op"], x["target"], x["reply_sid"]) for x in fs] == [("delete", r"C:\Users\Public\Desktop\a.docx", "")]
    st = {i["hostname"]: i["status"] for i in c.get("/api/work/pushed", headers=auth(t)).get_json()["items"]}
    assert st == {"A6-301-01": "deleted", "A6-301-02": "pending"}
    assert svc.flush_pending(world["ad"]) == 0  # vẫn tắt
    ag2 = _len(world, "A6-301-02")
    assert svc.flush_pending(world["ad"]) == 1 and svc.flush_pending(world["ad"]) == 0  # mỗi tệp chỉ gửi 1 lần
    assert [x["target"] for x in k.got(ag2, "fs_request")] == [r"C:\Users\Public\Desktop\a.docx"]
    # Lần giao mới: nhật ký bắt đầu sạch (bỏ dòng đã xoá xong)
    did = str(repo_for(db, world["tid"], "computers").find_one({"hostname": "A6-301-01"})["_id"])
    c.post("/api/work/send", json={"batch_id": bid, "device_ids": [did]}, headers=auth(t))
    assert repo_for(db, world["tid"], "pushed_files").count({"status": "deleted"}) == 0


def test_che_do_may_gv_va_chot_an_toan(world, db):
    ag, devs, rooms = _dung(world)
    c, t = world["c"], tok(world)
    bid = _lo(c, t, {"a.docx": b"A"})
    j = c.post("/api/work/send", json={"batch_id": bid, "room_ids": [rooms["Phòng 301 - A6"]], "mode": "teachers"},
               headers=auth(t)).get_json()
    assert [s["hostname"] for s in j["sent"]] == ["A6-301-GV"]
    for dest in (r"C:\Windows\System32", r"c:/program files (x86)/PhenikaaIT", r"D:\ProgramData\PhenikaaIT\x",
                 "BaiTap"):
        r = c.post("/api/work/send", json={"batch_id": bid, "room_ids": [rooms["Phòng 301 - A6"]],
                                           "dest_folder": dest}, headers=auth(t))
        assert r.status_code == 422, dest
    base = {"room_ids": [rooms["Phòng 301 - A6"]], "src_folder": r"C:\Users\Public\Desktop\BaiTap"}
    for bad in ({"patterns": ["../../Windows/*"]}, {"patterns": ["a\\b"]}, {"src_folder": "C:\\", "delete_after": True},
                {"src_folder": r"C:\Windows\Temp", "delete_after": True}, {"src_folder": "BaiTap"}):
        assert c.post("/api/work/collect", json={**base, **bad}, headers=auth(t)).status_code == 422, bad
    assert c.post("/api/work/send", json={"batch_id": "abcdef0123", "room_ids": [rooms["Phòng 301 - A6"]]},
                  headers=auth(t)).status_code == 404  # lô không tồn tại


# ====================================================================== THU BÀI
def test_thu_bai_trang_thai_tai_ve_va_cau_truc_thu(world, db):
    ag, _, rooms = _dung(world)
    ag2 = _len(world, "A6-301-02")
    c, t = world["c"], tok(world)
    r301 = rooms["Phòng 301 - A6"]
    bid = _lo(c, t, {"de.docx": b"DE"})
    c.post("/api/work/send", json={"batch_id": bid, "room_ids": [r301]}, headers=auth(t))  # 01 + 02 nhận giao bài
    ag2.disconnect()
    world["clock"][0] += 36  # 02 tắt hẳn; 01 vẫn bật
    world["ad"].state.ingest(k.heartbeat("A6-301-01", MAY["A6-301-01"][0], ip=MAY["A6-301-01"][1]), "127.0.0.1")
    j = c.post("/api/work/collect", json={"room_ids": [r301], "src_folder": r"C:\Users\Public\Desktop\BaiTap",
                                          "patterns": ["*.docx", "*.cpp"], "delete_after": True, "save_thu": True,
                                          "ca": "ca sang"}, headers=auth(t)).get_json()
    sid = j["session_id"]
    assert (j["expected"], j["total"], j["ca"]) == (2, 1, "Ca sáng")
    assert _cmd(ag["A6-301-01"], "collect_work")[0] == {
        "action": "collect_work", "session_id": sid, "src_folder": r"C:\Users\Public\Desktop\BaiTap",
        "patterns": ["*.docx", "*.cpp"], "upload_url": "/collect_upload", "delete_after": True}
    st = c.get(f"/api/work/collect/{sid}", headers=auth(t)).get_json()
    assert {r["hostname"]: r["status"] for r in st["results"]} == {"A6-301-01": "running", "A6-301-02": "offline"}
    body = _zip({"Bai1/main.cpp": b"int main(){}", "../../thoat.docx": b"X"})
    assert c.post("/collect_upload", data={"session_id": sid, "hostname": "A6-301-01",
                                           "file": (io.BytesIO(body), "A6-301-01.zip")}).get_json() == {"status": "ok"}
    c.post("/collect_report", json={"session_id": sid, "hostname": "A6-301-01", "status": "ok",
                                    "files": ["Bai1/main.cpp", "thoat.docx"], "deleted": True})
    st = c.get(f"/api/work/collect/{sid}", headers=auth(t)).get_json()
    r1 = next(r for r in st["results"] if r["hostname"] == "A6-301-01")
    assert st["complete"] is True and st["submitted"] == 1
    assert (r1["status"], r1["count"], r1["deleted"], r1["has_zip"], r1["saved_dir"]) == (
        "ok", 2, True, True, "Ca sáng/Phòng 301 - A6/A6-301-01")
    # Cấu trúc THU trên máy chủ (zip-slip bị gỡ)
    thu = sorted(x["key"].split("/thu/")[1] for x in repo_for(db, world["tid"], "file_metadata").find(
        {"scope": "storage", "area": "thu"}))
    assert thu == ["Ca sáng/Phòng 301 - A6/A6-301-01/Bai1/main.cpp", "Ca sáng/Phòng 301 - A6/A6-301-01/thoat.docx"]
    # Tải: 1 máy · tất cả (<Phòng>/<Máy>.zip) · từng tệp trong bài
    assert c.get(f"/api/work/collect/{sid}/hosts/A6-301-01/zip", headers=auth(t)).data == body
    allz = zipfile.ZipFile(io.BytesIO(c.get(f"/api/work/collect/{sid}/zip", headers=auth(t)).data))
    assert allz.namelist() == ["Phòng 301 - A6/A6-301-01.zip"] and allz.read(allz.namelist()[0]) == body
    ent = c.get(f"/api/work/collect/{sid}/hosts/A6-301-01/entries", headers=auth(t)).get_json()["items"]
    assert ent == [{"path": "Bai1/main.cpp", "size": 12}, {"path": "thoat.docx", "size": 1}]
    r = c.get(f"/api/work/collect/{sid}/hosts/A6-301-01/entry?path=Bai1/main.cpp", headers=auth(t))
    assert r.data == b"int main(){}" and bytes.fromhex(r.headers["X-File-Name"]).decode() == "main.cpp"
    assert c.get(f"/api/work/collect/{sid}/hosts/A6-301-02/zip", headers=auth(t)).status_code == 404


def test_thu_bai_bao_khong_co_bai_va_quyen(world, db):
    ag, devs, rooms = _dung(world)
    c, t = world["c"], tok(world)
    sid = c.post("/api/work/collect", json={"device_ids": [devs["A6-301-01"], devs["A6-301-GV"]],
                                            "src_folder": r"C:\BaiTap"}, headers=auth(t)).get_json()["session_id"]
    c.post("/collect_report", json={"session_id": sid, "hostname": "A6-301-01", "status": "nofile"})
    c.post("/collect_report", json={"session_id": sid, "hostname": "A6-301-GV", "status": "nofolder",
                                    "error": r"C:\BaiTap"})
    st = c.get(f"/api/work/collect/{sid}", headers=auth(t)).get_json()
    assert st["complete"] and {r["hostname"]: r["status"] for r in st["results"]} == {"A6-301-01": "nofile",
                                                                                      "A6-301-GV": "nofolder"}
    assert c.get(f"/api/work/collect/{sid}/zip", headers=auth(t)).status_code == 404  # chưa ai nộp
    # Tài khoản giới hạn phòng 301: không lưu THU, không thấy phiên của người khác, không đụng phòng 405
    pid = create_policy(db, world["tid"], "GS 301", permission_codes=["device.control"],
                        room_ids=[ObjectId(rooms["Phòng 301 - A6"])])["_id"]
    tsvc.create_user(db, world["tid"], "gs301", password="Gs@12345", policy_ids=[pid])
    g = tok(world, user="gs301", pw="Gs@12345")
    assert c.post("/api/work/collect", json={"room_ids": [rooms["Phòng 301 - A6"]], "src_folder": r"C:\BaiTap",
                                             "save_thu": True}, headers=auth(g)).status_code == 403
    assert c.get(f"/api/work/collect/{sid}", headers=auth(g)).status_code == 404
    bid = _lo(c, g, {"x.txt": b"x"})
    j = c.post("/api/work/send", json={"batch_id": bid, "room_ids": [rooms["Phòng 405 - A6"]]},
               headers=auth(g)).get_json()
    assert j["total"] == 0 and j["skipped"][0]["reason"].startswith("không có phòng này")
    assert c.post(f"/api/work/upload?name=y.txt&batch={bid}", data=b"y", headers=auth(t)).status_code == 200  # admin
    other = _lo(c, t, {"z.txt": b"z"})
    assert c.post(f"/api/work/upload?name=w.txt&batch={other}", data=b"w", headers=auth(g)).status_code == 403
