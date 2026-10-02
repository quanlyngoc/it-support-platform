# Sổ bàn giao tiến độ — ITSupportPlatform

> **Phiên Claude mới: đọc tệp này ngay sau `CLAUDE.md`, rồi làm tiếp từ mục "BƯỚC TIẾP THEO".**
> Mỗi khi xong một bước: cập nhật tệp này + bảng mục 14 của `CLAUDE.md` TRƯỚC khi sang bước khác,
> để nếu phiên bị dừng giữa chừng thì phiên sau vẫn biết chính xác đang ở đâu.
> Kế hoạch đầy đủ: `docs/plan/SoTay_ThucHien_ITMonitor_SaaS.html` (số bước bên dưới theo Sổ tay;
> tài liệu đó còn ghi `D:\Platform` — hiểu là `D:\ITSupportPlatform`).

Cập nhật lần cuối: 02/10/2026 (2.11 xong — dịch vụ PlatformCore đang chạy; kế: 3.3)

## Cách mở phiên mới để làm tiếp

1. Mở VS Code tại `D:\ITSupportPlatform` → mở Claude Code (CLAUDE.md và `.claude/settings.json` tự nạp).
2. Gõ: **"Đọc CLAUDE.md và docs/TIEN_DO.md rồi làm tiếp BƯỚC TIẾP THEO."**
3. Muốn mở lại đúng cuộc trò chuyện cũ: trong Claude Code gõ `/resume` (hoặc chạy `claude --continue` ở thư mục đã làm việc).
4. Kiểm nhanh trạng thái trước khi làm tiếp (tất cả phải xanh):
   ```powershell
   cd D:\ITSupportPlatform\platform-core
   uv run pytest -q                 # 62 passed, 2 skipped, 45 xfailed (xfail = hợp đồng agent v2 chờ 3.3)
   uv run ruff check .
   uv run pyright
   git -C D:\ITSupportPlatform status --short
   git -C D:\NetworkInventory status --short   # KHÔNG được có thay đổi do dự án mới
   ```

## Quyết định đã chốt (chi tiết trong docs/adr)

- Phương án 2 (song song, chuyển từng phòng) · Desktop Tauri 2 + React 19 + Vite 8 · Agent là phần mềm .exe có bộ cài
- Claude xây mới, dự án cũ CHỈ ĐỌC (rào: `.claude/settings.json` + hook `.claude/hooks/guard_readonly.py`)
- Python **3.14.8 đã chốt** (ADR-0012: chạy thật bằng gevent trên Atlas đạt)
- **CSDL dựng thử: MongoDB Atlas** (ADR-0013). Chuỗi kết nối ở `platform-core/.env` (`MONGO_URI`, đã `.gitignore`).
  Không ghi chuỗi kết nối vào tài liệu.
- **Giai đoạn dựng thử: BỎ QUA bảo mật** (chỉ đạo 02/10/2026). Chỗ cố ý làm lỏng gắn nhãn `HOAN_BAO_MAT`;
  khi hoàn thiện chạy `rg HOAN_BAO_MAT` để xử lý hết (mục "Hoãn bảo mật").
- **Người phụ trách cho phép làm tiếp không cần hỏi** (02/10/2026: "hiện tại sẽ đều yes hết"). Vẫn giữ: dự án cũ chỉ đọc,
  không đẩy (push) ra ngoài, không chạy lệnh cần Administrator.

## Đã xong

| Bước Sổ tay | Việc | Bằng chứng |
|---|---|---|
| 0.11 | Không gian xây mới + rào chỉ đọc | `.claude/settings.json`, hook + `platform-deployment/qa/test_guard_readonly.py` (6 test) |
| 2.2 | Khung 5 project, `.gitattributes`, `.gitignore`, `README.md`, `CLAUDE.md`, ADR-0001…0013, `docs/plan` | cây thư mục |
| 2.3 | uv 0.12.22, Python 3.14.8, `pyproject.toml`, `uv.lock` (+ pyright 1.1.414 kèm node riêng) | `uv run pyright` |
| 2.4 | Bí mật: `.env` trong `.gitignore` (gitleaks + thư mục bí mật ngoài repo → hoãn bảo mật) | `.gitignore` |
| 2.5 | `app/db`: client, 51 index (4A.30 bản V3), validator `$jsonSchema` moderate, seed 18 quyền, `init` | Atlas `itm_core`: 25 collection, 51 index, 18 quyền |
| 2.6 | `Ctx`, `TenantRepo` + `repo_for`, `require_refs` (4A.29), test cấm truy vấn trần | `tests/isolation/*` |
| 2.7 | CLI tạo tổ chức + Super Admin | Atlas: tổ chức `PHENIKAA`, tài khoản `admin` (mật khẩu: biến `DEV_ADMIN_PASSWORD` trong `platform-core/.env`) |
| 2.8 | `/api/auth/login|logout|me`: Local (Argon2id), AD (LDAP), TOTP, 1 thiết bị, giới hạn IP, sai mã tổ chức | `tests/unit/test_auth_api.py` |
| 2.9 | `require_perm`, audit after_request (LAB/HSK/THI), OpenAPI `/docs`, `app/server.py` gevent | chạy thật cổng 7009 trên Atlas: login 0,5 s, `/me` 11 ms (đệm) |
| 2.10 | 23 mục §4A.36 + §77 (`tests/isolation/test_spec_isolation.py`), CI `.github/workflows/ci.yml` | 21 xanh + 2 skip mức API (GĐ3, GĐ7) |
| — | Công cụ QA: `platform-deployment/qa/check_routes.py`, `check_eol.py` (+ test của chính công cụ) | cả hai ĐẠT |
| 2.11 | **Dịch vụ `PlatformCore` đã cài và chạy** (người vận hành cài tay bằng lệnh nssm, 02/10/2026). `dich_vu_core.ps1 -Lenh KiemTra`: Running, Delayed Auto (registry `DelayedAutostart=1`), LocalSystem, nghe 127.0.0.1:7009, ping Atlas 431 ms; `core-out.log` có 2 dòng khởi động (lần đầu + tự lên lại sau khi giết tiến trình), `core-err.log` trống; 7 dịch vụ hệ cũ vẫn Running | `dich_vu_core.ps1 -Lenh KiemTra` |
| 2.11 (chuẩn bị) | Script dịch vụ `platform-deployment/nssm/dich_vu_core.ps1` (CaiDat/KiemTra/CapNhat/Go) + bản chạy `D:\ITSupportPlatformRun` (clone `main`, `uv sync --no-dev --locked`); `HOST` (mặc định 127.0.0.1); `/api/health?db=1` | Chạy thử bằng tài khoản thường cổng 7019: nghe 127.0.0.1, ping Atlas 456 ms, giết tiến trình con → launcher thoát (NSSM sẽ thấy), giết launcher → con chết theo, nhả cổng; tham số nssm truyền đúng (thay nssm bằng chương trình ghi tham số) |
| 3.1 | Hợp đồng agent v2: `platform-core/tests/contract_v2/HOP_DONG.md` (luật sống còn A1–A11, thông số, 18 route HTTP, 15 sự kiện socket, 15 action lệnh) + 45 fixture + `test_contract_v2.py` | 3 test kiểm fixture xanh; 45 test hợp đồng `xfail strict` chờ 3.3 |

## Đang làm

- (không có — 3.1 xong; bước kế là 3.3 viết legacy_adapter. 3.2 là việc người vận hành)

## BƯỚC TIẾP THEO

1. **3.3 `app/legacy_adapter/`** theo Sổ tay + `HOP_DONG.md`: `state.py` (online + `REGISTERED` + hàng đợi lệnh HTTP + ACK
   trong RAM của 1 tiến trình), `http_routes.py`, `socket_handlers.py`, `dispatch.py` (không broadcast — luật A8),
   `results.py` (MongoDB `command_results`), `writer.py` (ghi `computers` gộp ở luồng nền — luật A10 + bài học 10.20/10.21),
   `update_gate.py` (luật A4/A5), `contract.py` (`apply_setup`, `check_socket` cho test hợp đồng). Đọc thêm (CHỈ ĐỌC)
   `D:\NetworkInventory\workers.py` (`async_db_writer_worker`, `_mevt_swap`, `_mevt_hwid`, `generic_serials`) và
   `utils.py` (`get_room_from_hostname`, `SystemState`). Mỗi mục làm xong → thêm id vào `IMPLEMENTED` trong test.
2. Bỏ `skip` của 2 test API trong `test_spec_isolation.py` khi module tương ứng xong (GĐ3: lệnh agent; GĐ7: tải tệp).
3. ⚠️ **Sửa Sổ tay bước 3.6 (canary Caddy)** theo `HOP_DONG.md` mục A11: agent gửi `User-Agent: Mozilla/5.0` ở
   `/check_update` + `/download_setup`, nên matcher canary phải là `client_ip` + **danh sách đường dẫn agent**, KHÔNG dùng
   `not header User-Agent *Mozilla*`. Áp vào `docs/plan/SoTay_*.html|docx` khi cập nhật tài liệu (cùng lúc đổi `D:\Platform`).

## Việc cần người vận hành (Claude không có quyền Administrator)

- [ ] Đẩy mã lần đầu: remote `origin` = github.com/quanlyngoc/it-support-platform đã đặt; người vận hành chạy
      `git push -u origin main` → CI tự chạy (kiểm lại phiên bản `actions/checkout`, `astral-sh/setup-uv` mới nhất).
- [x] 2.11: dịch vụ `PlatformCore` đã cài (02/10/2026). Khi có mã mới cần chạy trên dịch vụ: PowerShell **Run as Administrator** →
      `Set-ExecutionPolicy -Scope Process Bypass -Force; & D:\ITSupportPlatform\platform-deployment\nssm\dich_vu_core.ps1 -Lenh CapNhat`
      (máy chủ thiếu System32 trong PATH nên KHÔNG gõ `powershell -File ...`; Claude không tự làm được vì cần dừng dịch vụ).
- [ ] 3.2, 3.5–3.9: các bước sửa Caddy (canary) — chỉ làm khi đã có legacy_adapter và có người trực.
- [ ] Cài Node.js 24 LTS, Rust, VS Build Tools trên máy phát triển desktop-app (GĐ4).
- [ ] Bước 0.6, 0.7 (sao lưu hằng ngày, cảnh báo online tụt) trên máy chủ hệ cũ.

## Hoãn bảo mật (làm ở giai đoạn hoàn thiện, trước khi chạy thật)

- [ ] Atlas: đổi mật khẩu `admin` (đã xuất hiện trong khung chat), tạo user riêng `core_app` (readWrite `itm_core`),
      `master_app` (readWrite `itm_master`); giới hạn Network Access theo IP công khai của máy chủ.
- [ ] Đổi mật khẩu tài khoản `admin` của tổ chức PHENIKAA (đang là mật khẩu dựng thử trong `.env`).
- [ ] Đặt `MASTER_KEY_B64` riêng (đang dùng khoá dev mặc định trong `app/config/settings.py`); `ALLOWED_ORIGINS` theo Desktop.
- [ ] Rà mọi nhãn `HOAN_BAO_MAT` trong mã (`rg HOAN_BAO_MAT D:\ITSupportPlatform`).
- [ ] Bí mật chuyển ra ngoài repo (`D:\ITSupportPlatformSecrets`), khoá quyền thư mục; bật gitleaks pre-commit (Sổ tay 2.4).
- [ ] Luật Bảo vệ dữ liệu cá nhân 2025: kiểm region Atlas và thoả thuận xử lý dữ liệu.

## Ghi chú hạ tầng

- Atlas: MongoDB **8.0.34**, replica set `atlas-m146mq-shard-0`, 3 node, RTT ≈ **55 ms** từ máy chủ hiện tại (đo 02/10/2026).
- Database: `itm_core` (Core, đã khởi tạo) · `itm_master` (chưa dùng, GĐ11) · test tạo `itm_test_<hex>` rồi tự xoá.
  Atlas còn sẵn `sample_mflix` (dữ liệu mẫu của Atlas, không liên quan).
- Hiệu năng đo được: đăng nhập ≈ 0,5 s (≈ 8 lượt CSDL), kiểm phiên lần đầu ≈ 190 ms, có đệm ≈ 11 ms.
- Chạy thử Core khi phát triển: `cd D:\ITSupportPlatform\platform-core; $env:PORT='7019'; uv run python -m app.server`
  → `http://127.0.0.1:7019/docs`. **Cổng 7009 dành cho dịch vụ `PlatformCore`** — chạy thử dùng cổng khác (7019),
  xong nhớ tắt (chỉ dừng tiến trình có `app.server` trong dòng lệnh).
- Dịch vụ `PlatformCore` chạy từ `D:\ITSupportPlatformRun` (bản sao `main`), nhật ký `D:\ITSupportPlatformRun\logs\core-*.log`.
  Python của `.venv` là launcher (46 KB) gọi sang Python thật trong `%APPDATA%\uv\python\…` của tài khoản
  `anh.nguyennhuhoang` — LocalSystem đọc được; đừng xoá Python 3.14 đó bằng `uv python uninstall`.
  Khởi động lần đầu ≈ 13 s (biên dịch .pyc), ping Atlas lần đầu ≈ 0,5 s.
- Console máy chủ dùng cp1252: CLI phải gọi `utf8_stdio()`; script thử bằng Python thì đặt `PYTHONIOENCODING=utf-8`.
