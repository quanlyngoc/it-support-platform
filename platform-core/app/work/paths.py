"""Luật làm sạch ĐƯỜNG DẪN CON của tệp giao bài — BẢN SAO từng ký tự của `_duong_con_agent` (agent client.py).

🔴 BẤT BIẾN 4 NƠI (hệ cũ đã là 3 nơi): hệ thi `shared/duong_con.py` · hub cũ `app.py _duong_con_work` · agent
`client.py _duong_con_agent` · Core (tệp này). Agent tải tệp theo TÊN Core gửi (`/work_file/<lô>/<tên>`) nhưng LƯU theo
`_duong_con_agent(tên)`; Core ghi sổ `pushed_files` theo tên agent báo về. Lệch luật là "đẩy đi một đằng, xoá một nẻo".
Core dùng đúng bản của AGENT (agent quyết định tệp nằm đâu) và gửi xuống tên ĐÃ ở điểm bất động của luật đó
(`on_dinh`) → agent làm sạch lại vẫn ra đúng tên ấy. Kiểm bằng tests/unit/test_work_paths.py (chép nguyên hàm của
agent làm mẫu đối chiếu).

Luật: tách theo "/" lẫn "\\"; bỏ "" và "."; gặp ".." ở BẤT KỲ đâu → vứt thư mục, chỉ giữ tên trần (không đoán ý); bỏ
ký tự Windows cấm + điều khiển; bỏ dấu chấm/cách cuối; chặn tên thiết bị DOS; ≤ 120 ký tự/thành phần, ≤ 8 cấp thư mục
(+ tên tệp), ≤ 400 ký tự cả đường; không bao giờ rỗng ("file").
"""
from __future__ import annotations

import re

_DC_CAM = re.compile(r'[<>:"|?*\x00-\x1f]')
_DC_TB = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)
DESKTOP_CHUNG = r"C:\Users\Public\Desktop"  # agent: resolve_dest_folder("") = %PUBLIC%\Desktop


def duong_con(ten: object, sau_toi_da: int = 8) -> str:
    """Đúng `_duong_con_agent` của agent 2.7.5.x — ĐỪNG sửa riêng ở đây."""
    tho = str(ten or "").replace("\\", "/")
    phan = [p for p in tho.split("/") if p not in ("", ".")]
    if any(p == ".." for p in phan):
        phan = phan[-1:]
    sach = []
    for p in phan:
        s = _DC_CAM.sub("", p).strip().rstrip(". ")
        if not s or s in (".", ".."):
            continue
        if _DC_TB.match(s):
            s = "_" + s
        sach.append(s[:120])
    if not sach:
        return "file"
    if len(sach) > sau_toi_da + 1:
        sach = sach[:1] + sach[-sau_toi_da:]
    return "/".join(sach)[:400]


def on_dinh(ten: object) -> str:
    """Áp luật tới điểm bất động: cắt 120/400 ký tự có thể để lại dấu cách/chấm ở cuối một thành phần → lần làm sạch
    sau (ở agent) sẽ ra tên KHÁC. Tên Core gửi xuống luôn là tên agent làm sạch lại vẫn y nguyên."""
    s = duong_con(ten)
    for _ in range(4):
        t = duong_con(s)
        if t == s:
            return s
        s = t
    return s


def full_path(dest_dir: str, rel: str) -> str:
    """Đường dẫn tuyệt đối trên máy trạm của tệp đã giao (khớp `os.path.join(dest_dir, *rel.split('/'))` của agent)."""
    return dest_dir.rstrip("\\/") + "\\" + rel.replace("/", "\\")


def dest_dir(dest: object) -> str:
    """Thư mục đích thật: rỗng = Desktop chung (như resolve_dest_folder của agent)."""
    d = str(dest or "").strip()
    return d or DESKTOP_CHUNG


def norm_ca(v: object) -> str:
    """'Ca sáng' | 'Ca chiều' | '' (như _thu_norm_ca hệ cũ)."""
    s = str(v or "").strip().lower()
    if "sáng" in s or "sang" in s:
        return "Ca sáng"
    if "chiều" in s or "chieu" in s:
        return "Ca chiều"
    return ""
