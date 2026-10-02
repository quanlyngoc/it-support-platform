"""Test hợp đồng agent v2 (Sổ tay 3.1). Mỗi fixture trong fixtures/ là một test.

Chưa có legacy_adapter (bước 3.3) nên mọi test hợp đồng đang `xfail(strict=True)`: khi adapter làm đúng, test tự qua →
pytest báo XPASS(strict) = ĐỎ → thêm id vào IMPLEMENTED để test thành xanh chính thức. Nhờ vậy không mục nào bị quên.

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
IMPLEMENTED: set[str] = set()  # id fixture đã có adapter phục vụ đúng (điền ở bước 3.3)


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
    from app.legacy_adapter import contract  # type: ignore[attr-defined]  # có ở bước 3.3

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
