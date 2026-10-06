"""Luật đường dẫn con của tệp giao bài (Sổ tay 7.3) — BẤT BIẾN 4 NƠI (hệ thi · hub cũ · agent · Core).

Mẫu đối chiếu là BẢN CHÉP NGUYÊN VĂN `_duong_con_agent` của agent 2.7.5.x (D:\\NetworkInventory\\agent_build\\client.py,
chỉ đọc): agent quyết định tệp nằm đâu trên máy trạm, Core phải ra ĐÚNG như vậy — lệch là "đẩy một đằng, xoá một nẻo".
"""
from __future__ import annotations

import random
import re

from app.work.paths import duong_con, full_path, norm_ca, on_dinh

# ---------------------------------------------------------------- BẢN CHÉP của agent (đừng sửa theo Core)
_DC_CAM_AG = re.compile(r'[<>:"|?*\x00-\x1f]')
_DC_TB_AG = re.compile(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$', re.I)


def _duong_con_agent(ten, sau_toi_da=8):
    tho = str(ten or '').replace('\\', '/')
    phan = [p for p in tho.split('/') if p not in ('', '.')]
    if any(p == '..' for p in phan):
        phan = phan[-1:]
    sach = []
    for p in phan:
        s = _DC_CAM_AG.sub('', p).strip().rstrip('. ')
        if not s or s in ('.', '..'):
            continue
        if _DC_TB_AG.match(s):
            s = '_' + s
        sach.append(s[:120])
    if not sach:
        return 'file'
    if len(sach) > sau_toi_da + 1:
        sach = sach[:1] + sach[-sau_toi_da:]
    return '/'.join(sach)[:400]


# Ca thử của hệ thi (D:\ExaminationSystem\tests\test_day_ca_thu_muc.py) — cả 4 bản phải cùng ra kết quả này
CA = [
    ("DeThi/Phan1/bai.mp3", "DeThi/Phan1/bai.mp3"),
    ("DeThi\\Phan1\\bai.mp3", "DeThi/Phan1/bai.mp3"),
    ("bai.mp3", "bai.mp3"),
    ("./DeThi//Phan1/./bai.mp3", "DeThi/Phan1/bai.mp3"),
    ("../../Windows/System32/x.dll", "x.dll"),
    ("DeThi/../../../etc/passwd", "passwd"),
    ("D:/DeThi/bai.mp3", "D/DeThi/bai.mp3"),
    ("/abs/bai.mp3", "abs/bai.mp3"),
    ("CON/bai.mp3", "_CON/bai.mp3"),
    ("a<b>c/ba?i*.mp3", "abc/bai.mp3"),
]


def test_ca_thu_cua_he_thi():
    for vao, mong in CA:
        assert duong_con(vao) == _duong_con_agent(vao) == mong, vao
    assert duong_con("") == duong_con("   ") == "file"
    assert duong_con("/".join(f"t{i}" for i in range(20)) + "/x.mp3").count("/") <= 9


def test_trung_khop_ban_agent_va_diem_bat_dong():
    rnd = random.Random(7)
    abc = list("aZ09 .-_/\\:*?<>|\"") + ["..", "con", "LPT1", "Đề", "bài thi", "\x01", " .", ". "]
    mau = [*(v for v, _ in CA), "a" * 119 + " b/c.txt", "x" * 130 + ".docx", "a/" * 30 + "b", "q " * 250 + ".mp3",
           "con.txt", "Thư mục/  khoảng trắng  /tệp .txt", "x" * 119 + "./y"]
    mau += ["".join(rnd.choice(abc) for _ in range(rnd.randint(1, 60))) for _ in range(3000)]
    for s in mau:
        assert duong_con(s) == _duong_con_agent(s), repr(s)
        t = on_dinh(s)
        assert _duong_con_agent(t) == t, repr(s)  # tên Core gửi xuống: agent làm sạch lại vẫn y nguyên
        assert t and not t.startswith("/") and ".." not in t.split("/")


def test_duong_dan_tren_may_tram_va_ca_thi():
    assert full_path(r"C:\BaiTap", "DeThi/Phan1/bai.mp3") == r"C:\BaiTap\DeThi\Phan1\bai.mp3"
    assert full_path("C:\\BaiTap\\", "a.docx") == r"C:\BaiTap\a.docx"
    assert (norm_ca("ca sang"), norm_ca("Ca chiều"), norm_ca("tối")) == ("Ca sáng", "Ca chiều", "")
