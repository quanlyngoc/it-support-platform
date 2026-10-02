"""Test hợp đồng agent v2 (Sổ tay 3.1). Mỗi fixture trong fixtures/ là một test.

Fixture có id trong IMPLEMENTED là test xanh bắt buộc. Fixture MỚI thêm vào (chưa có trong IMPLEMENTED) tự chạy dạng
`xfail(strict=True)`: khi adapter làm đúng, test tự qua → pytest báo XPASS(strict) = ĐỎ → thêm id vào IMPLEMENTED.
Nhờ vậy không mục nào bị quên.

Adapter phải cung cấp `app.legacy_adapter.contract` với:
    apply_setup(app, step: str) -> None          # các bước "setup" trong fixture (agent_registered:..., fs_token:...)
    check_socket(app, fixture: dict) -> None     # phát/nhận sự kiện socket và assert "effect"
"""
from __future__ import annotations

import base64
import io
import json
import pathlib

import pytest

FIX_DIR = pathlib.Path(__file__).parent / "fixtures"
FIXTURES = sorted((json.loads(p.read_text(encoding="utf-8")) for p in FIX_DIR.glob("*.json")), key=lambda f: f["id"])
IMPLEMENTED: set[str] = {  # id fixture adapter đã phục vụ đúng (bước 3.3 xong 02/10/2026: đủ 45/45)
    "http_check_command_empty", "http_check_command_obj", "http_check_command_str", "http_check_update_closed",
    "http_check_update_open", "http_check_update_probe", "http_client_log", "http_collect_report",
    "http_collect_upload", "http_collect_upload_unknown", "http_download_setup", "http_fs_bridge_pending",
    "http_fs_recv_legacy", "http_fs_recv_raw", "http_fs_recv_raw_bad_token", "http_fs_serve", "http_login_result",
    "http_offline", "http_ps_auth_result", "http_ps_bulk_result_ok", "http_ps_bulk_result_unknown",
    "http_pty_auth_result", "http_send_report", "http_update_boot_placeholders", "http_update_dang_tat",
    "http_update_missing_hostname", "http_update_no_socket", "http_update_ok", "http_update_old_version_no_426",
    "http_work_file", "sock_in_client_ps_output", "sock_in_client_pty_output", "sock_in_client_update_legacy",
    "sock_in_cmd_ack", "sock_in_disconnect", "sock_in_fs_progress", "sock_in_fs_response", "sock_in_register",
    "sock_in_vnc_thumb", "sock_out_execute_command", "sock_out_fs_request", "sock_out_server_ps_input",
    "sock_out_server_pty_input", "sock_out_server_pty_resize", "sock_out_vnc_thumb_req"
}


def _param(f: dict):
    marks = [] if f["id"] in IMPLEMENTED else [pytest.mark.xfail(strict=True, reason="chờ legacy_adapter (Sổ tay 3.3)")]
    return pytest.param(f, id=f["id"], marks=marks)


# ---------------- Bộ fixture phải hợp lệ (xanh ngay từ bây giờ) ----------------
def test_fixture_hop_le_va_khong_trung():
    assert len(FIXTURES) >= 40
    ids = [f["id"] for f in FIXTURES]
    assert len(ids) == len(set(ids))
    for f in FIXTURES:
        assert f["kind"] in ("http", "socket_in", "socket_out"), f["id"]
        assert f.get("source"), f["id"]
        if f["kind"] == "http":
            assert f["request"]["method"] in ("GET", "POST") and f["request"]["path"].startswith("/"), f["id"]
            assert f["expect"]["status"], f["id"]
        else:
            assert f.get("event") and f.get("effect"), f["id"]


def test_moi_route_va_su_kien_trong_hop_dong_deu_co_fixture():
    doc = (pathlib.Path(__file__).parent / "HOP_DONG.md").read_text(encoding="utf-8")
    routes = {"/update", "/check_update", "/download_setup", "/client_log", "/offline", "/check_command/",
              "/login_result/", "/ps_auth_result/", "/pty_auth_result/", "/ps_bulk_result/", "/send_report",
              "/work_file/", "/collect_upload", "/collect_report", "/fs_recv_raw", "/fs_recv", "/fs_serve/",
              "/fs_bridge/"}
    events = {"register", "disconnect", "cmd_ack", "client_ps_output", "client_pty_output", "fs_progress",
              "fs_response", "vnc_thumb", "client_update", "execute_command", "server_ps_input", "server_pty_input",
              "server_pty_resize", "fs_request", "vnc_thumb_req"}
    paths = [f["request"]["path"] for f in FIXTURES if f["kind"] == "http"]
    for r in routes:
        assert r in doc, f"HOP_DONG.md thiếu {r}"
        assert any(p == r or p.startswith(r) for p in paths), f"thiếu fixture cho {r}"
    got = {f["event"] for f in FIXTURES if f["kind"] != "http"}
    assert events <= got, f"thiếu fixture socket: {events - got}"
    for e in events:
        assert f"`{e}`" in doc, f"HOP_DONG.md thiếu sự kiện {e}"


def test_luat_song_con_nhip_tim_luon_200():
    # A1/A2: mọi fixture /update đều kỳ vọng 200, không fixture nào chấp nhận 426
    for f in FIXTURES:
        if f["kind"] == "http" and f["request"]["path"] == "/update":
            assert f["expect"]["status"] == [200], f["id"]


# ---------------- Test hợp đồng (đỏ có chủ đích tới bước 3.3) ----------------
def _contract():
    from app.legacy_adapter import contract

    return contract


def _send(client, req: dict):
    kw: dict = {"headers": req.get("headers") or {}}
    if "json" in req:
        kw["json"] = req["json"]
    if "query" in req:
        kw["query_string"] = req["query"]
    if "raw" in req:
        kw["data"] = base64.b64decode(req["raw"])
    if "form" in req:
        data = {}
        for k, v in req["form"].items():
            data[k] = (io.BytesIO(base64.b64decode(v["content_b64"])), v["filename"]) if isinstance(v, dict) else v
        kw["data"] = data
        kw["content_type"] = "multipart/form-data"
    return client.open(req["path"], method=req["method"], **kw)


@pytest.mark.parametrize("fx", [_param(f) for f in FIXTURES if f["kind"] == "http"])
def test_http(fx, app):
    contract = _contract()
    for step in fx["setup"]:
        contract.apply_setup(app, step)
    r = _send(app.test_client(), fx["request"])
    exp = fx["expect"]
    assert r.status_code in exp["status"], (r.status_code, r.data[:200])
    if exp.get("binary"):
        if r.status_code == 200:
            assert r.data and not r.is_json
        return
    body = r.get_json(silent=True)
    for k, v in (exp.get("json_subset") or {}).items():
        assert body is not None and body.get(k) == v, (k, body)
    for k in exp.get("json_keys") or []:
        assert body is not None and k in body, (k, body)


@pytest.mark.parametrize("fx", [_param(f) for f in FIXTURES if f["kind"] != "http"])
def test_socket(fx, app):
    contract = _contract()
    for step in fx["setup"]:
        contract.apply_setup(app, step)
    contract.check_socket(app, fx)
