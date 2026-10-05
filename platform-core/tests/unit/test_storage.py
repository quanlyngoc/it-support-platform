# pyright: reportOptionalSubscript=false, reportOptionalMemberAccess=false
"""Sổ tay 7.1: StorageService bản cục bộ — luật khoá (ranh giới tổ chức, chặn `..`), ghi nguyên tử theo luồng (không
nạp cả tệp vào RAM), sổ file_metadata có hạn dọn theo khu, worker CHỈ xoá thứ đã ghi sổ; agent v2 dùng chung kho."""
from __future__ import annotations

import hashlib
import io
import os
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from bson import ObjectId

from app.storage import KhoaSai, KhongCo, LocalFS, QuaLon, TenantFiles, key_for, safe_parts, safe_segment
from app.storage.keys import parse
from app.storage.sweeper import sweep
from app.tenants.repo import repo_for

T0 = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


# ====================================================================== khoá
def test_khoa_dung_luat_va_ranh_gioi_to_chuc():
    a, b = ObjectId(), ObjectId()
    k = key_for(a, "work", "ab12", "De thi/bài 1.docx")
    assert k == f"tenants/{a}/work/ab12/De thi/bài 1.docx"
    assert parse(k, a) == (str(a), "work", ["ab12", "De thi", "bài 1.docx"])
    with pytest.raises(KhoaSai):
        parse(k, b)  # khoá của tổ chức khác
    sai = [f"tenants/{a}/work/../x", f"tenants/{a}/work/a\\b", f"/tenants/{a}/work/x", f"tenants/{a}/khac/x",
           f"tenants/{a}/work", f"tenants/{a}/work/a//b", f"tenants/{a}/work/CON", f"tenants/{a}/work/con.txt",
           f"tenants/{a}/work/bai.", f"tenants/{a}/work/bai ", f"tenants/{a}/work/a:b", f"tenants/{a}/work/a\x01",
           f"tenants/{str(a)[:-1]}/work/x", "tenants/../work/x", ""]
    for s in sai:
        with pytest.raises(KhoaSai):
            parse(s)
    with pytest.raises(KhoaSai):
        key_for(a, "work", "..", "x")  # key_for KIỂM chứ không tự sửa


def test_ten_tep_an_toan_giu_tieng_viet():
    assert safe_segment("..\\..\\Windows\\win.ini") == "win.ini"
    assert safe_segment("Đề thi: số 1?.docx") == "Đề thi_ số 1_.docx"
    assert safe_segment("CON") == "_CON" and safe_segment("bài.  ") == "bài" and safe_segment("") == "file"
    assert len(safe_segment("a" * 300 + ".docx")) == 200 and safe_segment("a" * 300 + ".docx").endswith(".docx")
    assert safe_parts("../De thi/./bài 1\\..\\de.docx") == ["De thi", "bài 1", "de.docx"]
    assert safe_parts("..") == ["file"]


# ====================================================================== LocalFS
def test_localfs_ghi_doc_liet_ke_xoa(tmp_path):
    fs, a = LocalFS(tmp_path), ObjectId()
    k = key_for(a, "collected", "c0ffee", "A6-301-01.zip")
    body = [b"PK\x03\x04", b"x" * 300_000, b"het"]
    r = fs.put_stream(k, iter(body))
    assert (r.size, r.sha256) == (300_007, hashlib.sha256(b"".join(body)).hexdigest())
    with fs.get_stream(k) as f:
        assert f.read() == b"".join(body)
    assert fs.local_path(k) == tmp_path / "tenants" / str(a) / "collected" / "c0ffee" / "A6-301-01.zip"
    assert [o.key for o in fs.list(f"tenants/{a}")] == [k] == [o.key for o in fs.list(f"tenants/{a}/collected/")]
    assert fs.stat(k).size == 300_007
    with pytest.raises(KhoaSai):
        fs.list("tenants")  # không bao giờ liệt kê chéo tổ chức
    fs.put_stream(k, io.BytesIO(b"ban moi"))  # ghi đè
    assert fs.get_stream(k).read() == b"ban moi"
    assert fs.delete(k) is True and fs.delete(k) is False
    assert not (tmp_path / "tenants" / str(a) / "collected" / "c0ffee").exists()  # thư mục rỗng được dọn
    assert (tmp_path / "tenants" / str(a) / "collected").is_dir()  # …nhưng giữ thư mục khu
    with pytest.raises(KhongCo):
        fs.get_stream(k)


def test_localfs_loi_giua_chung_khong_de_lai_gi(tmp_path):
    fs, a = LocalFS(tmp_path), ObjectId()
    k = key_for(a, "temp", "fs", "x.bin")
    fs.put_stream(k, io.BytesIO(b"ban cu"))

    def hong():
        yield b"nua chung"
        raise ConnectionError("agent rớt mạng")

    with pytest.raises(ConnectionError):
        fs.put_stream(k, hong())
    with pytest.raises(QuaLon):
        fs.put_stream(k, io.BytesIO(b"x" * 1000), max_bytes=999)
    assert fs.get_stream(k).read() == b"ban cu"  # bản cũ nguyên vẹn (ghi nguyên tử)
    assert os.listdir(fs.local_path(k).parent) == ["x.bin"]  # không còn tệp .part


def test_localfs_khong_nap_ca_tep_vao_ram(tmp_path):
    fs, a = LocalFS(tmp_path), ObjectId()
    k = key_for(a, "work", "b1", "lon.iso")
    khoi = b"z" * 262144

    def nguon():
        for _ in range(256):  # 64 MB
            yield khoi

    tracemalloc.start()
    fs.put_stream(k, nguon())
    h = hashlib.sha256()
    with fs.get_stream(k) as f:
        while c := f.read(262144):
            h.update(c)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert fs.stat(k).size == 64 * 1024 * 1024 and peak < 4 * 1024 * 1024, peak


# ====================================================================== sổ + hạn dọn
def _kho(db, tmp_path, tid=None, clock=None):
    tid = tid or db.tenants.insert_one({"code": f"T{ObjectId()}"}).inserted_id
    clock = clock or [T0]
    return TenantFiles(db, tid, LocalFS(tmp_path), now=lambda: clock[0]), clock


def test_so_ghi_han_theo_khu(db, tmp_path):
    kho, _ = _kho(db, tmp_path)
    han = {area: kho.save(area, ["s1", "f.bin"], io.BytesIO(b"abc"), by="it01")["delete_after"]
           for area in ("temp", "work", "collected", "thu", "chat", "report")}
    def h(x):
        return x.replace(tzinfo=UTC) if x and x.tzinfo is None else x
    assert {a: h(v) for a, v in han.items()} == {"temp": T0 + timedelta(hours=48), "work": T0 + timedelta(hours=48),
                                                 "collected": T0 + timedelta(hours=168), "thu": None, "chat": None,
                                                 "report": None}
    d = kho.save("temp", "x.zip", io.BytesIO(b"abc"), name="Bài thi.zip", ttl=timedelta(hours=2))
    assert (d["name"], d["size"], d["sha256"], d["status"]) == ("Bài thi.zip", 3, hashlib.sha256(b"abc").hexdigest(),
                                                                 "ok")
    assert h(d["delete_after"]) == T0 + timedelta(hours=2)
    kho.save("collected", ["s2", "A.zip"], io.BytesIO(b"1"))
    kho.save("collected", ["s2", "B.zip"], io.BytesIO(b"2"))
    assert [x["key"].rsplit("/", 1)[-1] for x in kho.list("collected", "s2")] == ["A.zip", "B.zip"]
    assert kho.delete_under("collected", "s2") == 2 and kho.list("collected", "s2") == []


def test_so_khong_lot_sang_to_chuc_khac_va_khong_mo_coi(db, tmp_path):
    a, _ = _kho(db, tmp_path)
    b, _ = _kho(db, tmp_path)
    k = a.save("thu", ["Phong 301", "bai.mp3"], io.BytesIO(b"am thanh"))["key"]
    for f in (lambda: b.get(k), lambda: b.open(k), lambda: b.delete(k), lambda: b.local_path(k)):
        with pytest.raises(KhoaSai):
            f()
    assert a.get(k)["size"] == 8

    def hong():
        yield b"x"
        raise ConnectionError

    with pytest.raises(ConnectionError):
        a.save("work", ["b9", "hong.bin"], hong())
    assert repo_for(db, a.tid, "file_metadata").count({"scope": "storage"}) == 1  # dòng giữ chỗ đã được bỏ


def test_don_chi_xoa_thu_da_ghi_so(db, tmp_path):
    kho, _ = _kho(db, tmp_path)
    fs = kho.storage
    tam = kho.save("temp", ["fs", "abc_bai.zip"], io.BytesIO(b"t"))["key"]
    thu = kho.save("collected", ["c1", "A6-301-01.zip"], io.BytesIO(b"c"))["key"]
    giu = kho.save("thu", ["Ca sang", "bai.mp3"], io.BytesIO(b"h"))["key"]
    # Tệp người vận hành tự chép vào (KHÔNG có trong sổ) — cũ cỡ nào cũng không được xoá (bài học "ca thi")
    tay = tmp_path / "tenants" / str(kho.tid) / "work" / "Ca sang" / "de.docx"
    tay.parent.mkdir(parents=True)
    tay.write_bytes(b"de that")
    cu = (T0 - timedelta(days=30)).timestamp()
    os.utime(tay, (cu, cu))
    # Phần ghi dở bị bỏ: cũ → dọn; mới → để yên (có thể đang ghi)
    part_cu = tay.parent / f".up-{'a' * 32}.part"
    part_moi = tay.parent / f".up-{'b' * 32}.part"
    for p in (part_cu, part_moi):
        p.write_bytes(b"do")
    os.utime(part_cu, (cu, cu))
    now = T0 + timedelta(hours=49)
    os.utime(part_moi, (now.timestamp(), now.timestamp()))

    assert sweep(db, fs, now) == {"deleted": 1, "partials": 1}
    assert fs.stat(tam) is None and kho.get(tam) is None and fs.stat(thu) is not None
    assert tay.exists() and not part_cu.exists() and part_moi.exists()
    assert sweep(db, fs, T0 + timedelta(hours=169)) == {"deleted": 1, "partials": 1}  # .part "mới" giờ đã > 24 giờ
    assert fs.stat(thu) is None and fs.stat(giu) is not None and tay.exists() and not part_moi.exists()


def test_don_bo_qua_khoa_sai_tep_dang_mo_va_so_mo_coi(db, tmp_path, monkeypatch):
    a, _ = _kho(db, tmp_path)
    b, _ = _kho(db, tmp_path)
    fs = a.storage
    ka = a.save("thu", ["x", "bai.mp3"], io.BytesIO(b"cua A"))["key"]
    # Dòng sổ của B trỏ vào tệp của A (dữ liệu hỏng / cố ý) → KHÔNG xoá, gỡ hạn để khỏi lặp lại
    repo_for(db, b.tid, "file_metadata").insert_one({"scope": "storage", "key": ka, "status": "ok",
                                                      "delete_after": T0})
    # Tệp đang bị giữ (agent đang tải) → để lượt sau
    kb = b.save("temp", ["fs", "dang_tai.zip"], io.BytesIO(b"b"))["key"]
    goc = fs.delete

    def ban(key):
        if key == kb:
            raise PermissionError("đang mở")
        return goc(key)

    monkeypatch.setattr(fs, "delete", ban)
    # Sổ còn mà tệp đã mất (ai đó xoá tay) + dòng giữ chỗ của lần ghi chết giữa chừng
    kc = b.save("temp", ["fs", "mat.zip"], io.BytesIO(b"m"))["key"]
    os.remove(str(fs.local_path(kc)))
    repo_for(db, b.tid, "file_metadata").insert_one({"scope": "storage", "key": key_for(b.tid, "work", "z", "y"),
                                                      "status": "uploading", "delete_after": T0 + timedelta(days=1)})
    now = T0 + timedelta(hours=49)
    assert sweep(db, fs, now) == {"bad_key": 1, "busy": 1, "missing": 2}
    assert fs.stat(ka) is not None and fs.stat(kb) is not None
    assert repo_for(db, b.tid, "file_metadata").find_one({"key": ka})["delete_after"] is None
    monkeypatch.setattr(fs, "delete", goc)
    assert sweep(db, fs, now) == {"deleted": 1}  # tệp hết bị giữ → lượt sau xoá được
    assert fs.stat(kb) is None


# ====================================================================== agent v2 dùng chung kho
def test_agent_v2_luu_vao_kho_chung(world):
    c, ad = world["c"], world["ad"]
    root = Path(world["app"].config["ITM_SETTINGS"].DATA_DIR)
    base = root / "tenants" / str(world["tid"])
    store = ad.store()
    tok = store.new_fs_token()
    assert c.post(f"/fs_recv_raw?token={tok}&name=Bài thi.zip", data=b"PK bai lam").get_json() == {"status": "ok"}
    assert (base / "temp" / "fs" / f"{tok}_Bài thi.zip").read_bytes() == b"PK bai lam"
    r = c.get(f"/fs_bridge/{tok}")
    assert r.status_code == 200 and r.data == b"PK bai lam" and "B%C3%A0i%20thi.zip" in r.headers["Content-Disposition"]
    sid = store.create_session("collect", meta={"total": 1})
    r = c.post("/collect_upload", data={"session_id": sid, "hostname": "A6-301-01",
                                        "file": (io.BytesIO(b"PK thu bai"), "x.zip")})
    assert r.get_json() == {"status": "ok"}
    assert (base / "collected" / sid / "A6-301-01.zip").read_bytes() == b"PK thu bai"
    d = store.kho.get(f"tenants/{world['tid']}/collected/{sid}/A6-301-01.zip")
    assert d["size"] == 10 and d["delete_after"] is not None
    bid = "ba7c4000000000000000000000000001"
    store.kho.save("work", [bid, "De thi/bài 1.docx"], io.BytesIO(b"de"))
    assert c.get(f"/work_file/{bid}/De thi/bài 1.docx").data == b"de"
    for xau in (f"/work_file/{bid}/../../temp/fs/{tok}_Bài thi.zip", f"/work_file/{bid}/..%2F..%2Fx",
                f"/work_file/{bid}/khong_co.docx", "/work_file/zzz/De thi/bài 1.docx"):
        assert c.get(xau).status_code == 404, xau
    assert not (root / "PHENIKAA" / "fs_tmp").exists() and not (root / "PHENIKAA" / "collect").exists()
