# Sổ bàn giao tiến độ — ITSupportPlatform

> **Phiên Claude mới: đọc tệp này ngay sau `CLAUDE.md`, rồi làm tiếp từ mục "BƯỚC TIẾP THEO".**
> Mỗi khi xong một bước: cập nhật tệp này + bảng mục 14 của `CLAUDE.md` TRƯỚC khi sang bước khác,
> để nếu phiên bị dừng giữa chừng thì phiên sau vẫn biết chính xác đang ở đâu.
> Kế hoạch đầy đủ: `docs/plan/SoTay_ThucHien_ITMonitor_SaaS.html` (số bước bên dưới theo Sổ tay;
> tài liệu đó còn ghi `D:\Platform` — hiểu là `D:\ITSupportPlatform`).

Cập nhật lần cuối: 02/10/2026 tối (3.3 legacy_adapter xong; Sổ tay sửa theo thực tế; kế: CapNhat dịch vụ → 0.6/0.7 → canary 3.5–3.8)

## Cách mở phiên mới để làm tiếp

1. Mở VS Code tại `D:\ITSupportPlatform` → mở Claude Code (CLAUDE.md và `.claude/settings.json` tự nạp).
2. Gõ: **"Đọc CLAUDE.md và docs/TIEN_DO.md rồi làm tiếp BƯỚC TIẾP THEO."**
3. Muốn mở lại đúng cuộc trò chuyện cũ: trong Claude Code gõ `/resume` (hoặc chạy `claude --continue` ở thư mục đã làm việc).
4. Kiểm nhanh trạng thái trước khi làm tiếp (tất cả phải xanh):
   ```powershell
   cd D:\ITSupportPlatform\platform-core
   uv run pytest -q                 # 133 passed, 1 skipped (05b chờ GĐ7 tải tệp)
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
| 3.3 | `app/legacy_adapter/` (state · adapter · fastpath · http_routes · socket_handlers · writer · store · update_gate · identity · api · contract) — commit `db637ac` | 45/45 test hợp đồng xanh; test cô lập 07b chạy thật; unit A1–A10; Atlas: Writer ghi 30 máy/lượt. Thử tải: xem dòng "Thử tải 3.3" |
| 3.3 (thử tải) | Core cổng 7019 + DB tạm `itm_loadtest`, giả lập agent 2.7.5.3 (nhịp tim 2 s + poll 1,6–3 s + websocket register/ping/ACK), mọi tiến trình thử BelowNormal | 300 agent/90 s: qua Flask 28,5% một lõi, p99 ≈ 510 ms → thêm đường nhanh WSGI: **5%, p99 ≈ 3 ms**; tắt nhật ký truy cập gevent-websocket (≈ 10 GB/ngày). **900 agent/30 phút (ĐẠT điều kiện Sổ tay 3.3):** 810 nghìn nhịp tim (450/s) + 704 nghìn poll (391/s), **0 lỗi, 0 mã ≠ 200**, 900/900 socket không rớt; p50/p95/p99 nhịp tim 1,4/6/14 ms; CPU Core TB 22,5% (max 29,5%) một lõi; RAM 226 → 224 MB (không rò); CPU toàn máy TB 17,5%. Atlas: 900 `computers`, 26.700 phút `usage_stats`, 0 `machine_events`; ngắt socket → 900 máy offline ngay. DB tạm đã xoá |
| — | Sổ tay + Lộ trình theo thực tế (commit `90fe9f0`): `D:\ITSupportPlatform`, Atlas, Core cùng máy; canary A11 lọc IP + 19 đường dẫn — đã `caddy adapt` + `validate` trên bản sao Caddyfile (đứng trước `@hub`, `path` gộp HOẶC); 3.2 không bắt buộc; 3.4–3.8 viết lại với lệnh PowerShell + `/api/legacy/*`; docx dựng lại; artifact cập nhật (bản 3) | `docs/plan/*`, https://claude.ai/artifact/6YS1eX45UvaRHQGGQD3T9G |
| 3.3 (đưa lên dịch vụ) | Người vận hành chạy `dich_vu_core.ps1 -Lenh CapNhat` (02/10/2026 18:20) | `KiemTra`: bản `ac6d8a9` = main, có `DATA_DIR`, ping CSDL 53 ms; `/check_update` → `0.0.0.0`; `/update` → 200; 7 dịch vụ hệ cũ Running. Hai lần dừng/bật 18:20 + 18:21 là lệnh STOP có chủ đích (nhật ký NSSM), không phải sập |
| — | Core dừng êm khi NSSM gửi Ctrl+C (commit `d2aaaa8`): không còn ~30 dòng traceback `KeyboardInterrupt` trong `core-err.log` mỗi lần dừng | Thử: tắt phần chặn → stderr có traceback; bật → stderr trống, mã thoát 0. Có hiệu lực ở lần `CapNhat` kế |
| 0.6 + 0.7 (chuẩn bị) | `platform-deployment/ops/`: `sao_luu_csdl_cu.py` (API backup SQLite từ kết nối `mode=ro` — CSDL cũ chạy WAL, `-wal` 36 MB > tệp chính 30 MB nên chép thô là mất dữ liệu; giữ 14 bản + `may_<ngày>.csv`), `canh_bao_online.py` (mỗi phút đọc `/internal/machines`, Telegram khi rớt ≥ max(5, 10%), bỏ máy tắt có chủ ý + canary; báo khi mất hub 2 lần liên tiếp + khi hồi), `lay_cau_hinh_cu.py`, `cai_dat_ops.ps1` (CaiDat/KiemTra/Go) | 9 test mới trong `qa/test_ops.py`; chạy thật (không gửi Telegram): sao lưu 889 máy 29 MB ≈ 1 s, `-shm` hệ cũ không đổi; hub trả 48 online/48 còn kênh lệnh; trigger lặp mỗi phút mặc định vô hạn trên WS2019. Sổ tay 0.6/0.7 thêm "Cách nhanh" (artifact bản 4) |
| 3.1 | Hợp đồng agent v2: `platform-core/tests/contract_v2/HOP_DONG.md` (luật sống còn A1–A11, thông số, 18 route HTTP, 15 sự kiện socket, 15 action lệnh) + 45 fixture + `test_contract_v2.py` | 3 test kiểm fixture xanh; 45 test hợp đồng `xfail strict` chờ 3.3 |

## Đang làm

- (không có)

## BƯỚC TIẾP THEO

1. **Người vận hành: cài 0.6 + 0.7** (điều kiện bắt buộc trước canary) — PowerShell Run as Administrator:
   `Set-ExecutionPolicy -Scope Process Bypass -Force; & D:\ITSupportPlatform\platform-deployment\ops\cai_dat_ops.ps1 -Lenh CaiDat`
   Đạt khi in đủ [ĐẠT] (sao lưu thử, tin thử Telegram tới nhóm, baseline có dòng). Sau đó Claude kiểm bằng `-Lenh KiemTra`.
2. Theo dõi baseline vài ngày (`D:\Backup\baseline\online_<ngày>.csv`) để biết ngưỡng cảnh báo có gây báo động giả giờ tan
   học không (Sổ tay 0.8 dùng chính số liệu này).
3. **Canary 1 máy (3.5 → 3.8)** theo Sổ tay đã sửa: chọn máy thử không dạy, người trực có mặt; ghi tên máy vào
   `D:\Backup\baseline\canary_hosts.txt` TRƯỚC khi sửa Caddy (để 0.7 không báo máy đó "rớt"); khối Caddy ở 3.6 đã kiểm sẵn.
4. Phần còn lại của 3.3 ghi ở `HOP_DONG.md` mục H "Chưa làm": cảnh báo đổi RAM/ổ cứng → `incidents`; dọn tệp cũ trong
   `DATA_DIR`; API phiên giao/thu bài + token truyền tệp cho Desktop (GĐ7); `/internal/*` cho hệ thi (GĐ9).
5. GĐ4 Desktop chờ người vận hành cài Node.js 24 LTS + Rust + VS Build Tools trên máy phát triển.

## Việc cần người vận hành (Claude không có quyền Administrator)

- [ ] Đẩy mã lần đầu: remote `origin` = github.com/quanlyngoc/it-support-platform đã đặt; người vận hành chạy
      `git push -u origin main` → CI tự chạy (kiểm lại phiên bản `actions/checkout`, `astral-sh/setup-uv` mới nhất).
- [x] 2.11: dịch vụ `PlatformCore` đã cài (02/10/2026). Khi có mã mới cần chạy trên dịch vụ: PowerShell **Run as Administrator** →
      `Set-ExecutionPolicy -Scope Process Bypass -Force; & D:\ITSupportPlatform\platform-deployment\nssm\dich_vu_core.ps1 -Lenh CapNhat`
      (máy chủ thiếu System32 trong PATH nên KHÔNG gõ `powershell -File ...`; Claude không tự làm được vì cần dừng dịch vụ).
- [x] `dich_vu_core.ps1 -Lenh CapNhat` — dịch vụ chạy mã 3.3 (02/10/2026 18:20).
- [ ] Bước 0.6, 0.7: `platform-deployment\ops\cai_dat_ops.ps1 -Lenh CaiDat` (xem BƯỚC TIẾP THEO 1).
- [ ] 3.5–3.9: canary bằng Caddy — chỉ làm sau khi 0.6 + 0.7 chạy và có người trực (3.2 không còn bắt buộc).
- [ ] Cài Node.js 24 LTS, Rust, VS Build Tools trên máy phát triển desktop-app (GĐ4).

## Hoãn bảo mật (làm ở giai đoạn hoàn thiện, trước khi chạy thật)

- [ ] Atlas: đổi mật khẩu `admin` (đã xuất hiện trong khung chat), tạo user riêng `core_app` (readWrite `itm_core`),
      `master_app` (readWrite `itm_master`); giới hạn Network Access theo IP công khai của máy chủ.
- [ ] Đổi mật khẩu tài khoản `admin` của tổ chức PHENIKAA (đang là mật khẩu dựng thử trong `.env`).
- [ ] Đặt `MASTER_KEY_B64` riêng (đang dùng khoá dev mặc định trong `app/config/settings.py`); `ALLOWED_ORIGINS` theo Desktop.
- [ ] Rà mọi nhãn `HOAN_BAO_MAT` trong mã (`rg HOAN_BAO_MAT D:\ITSupportPlatform`).
- [ ] Bí mật chuyển ra ngoài repo (`D:\ITSupportPlatformSecrets`), khoá quyền thư mục; bật gitleaks pre-commit (Sổ tay 2.4).
- [ ] Luật Bảo vệ dữ liệu cá nhân 2025: kiểm region Atlas và thoả thuận xử lý dữ liệu.
- [ ] **Hệ cũ** dùng token `/internal/*` = giá trị MẶC ĐỊNH ghi cứng trong `D:\NetworkInventory\app.py` `_internal_token()`
      (không đặt env `INTERNAL_API_TOKEN` lẫn `settings.internal_api_token`; ThiHSK dùng cùng giá trị). Khi hoàn thiện: đặt token
      riêng cho hub + ThiHSK + `D:\ITSupportPlatformSecrets\internal_token.txt` cùng lúc. Claude KHÔNG sửa hệ cũ — chỉ ghi nhận.

## Ghi chú hạ tầng

- Atlas: MongoDB **8.0.34**, replica set `atlas-m146mq-shard-0`, 3 node, RTT ≈ **55 ms** từ máy chủ hiện tại (đo 02/10/2026).
- Database: `itm_core` (Core, đã khởi tạo) · `itm_master` (chưa dùng, GĐ11) · test tạo `itm_test_<hex>` rồi tự xoá.
  Atlas còn sẵn `sample_mflix` (dữ liệu mẫu của Atlas, không liên quan).
- Hiệu năng đo được: đăng nhập ≈ 0,5 s (≈ 8 lượt CSDL), kiểm phiên lần đầu ≈ 190 ms, có đệm ≈ 11 ms.
- Thử tải agent v2 (02/10/2026): xem dòng "3.3 (thử tải)" ở bảng Đã xong. Lặp lại: scratchpad `loadgen.py` + `run_load.ps1`
  (DB tạm `itm_loadtest`, cổng 7019, mọi tiến trình BelowNormal; thử xong xoá DB tạm). Đường nhanh WSGI là lý do đạt — đừng gỡ.
- Chạy thử Core khi phát triển: `cd D:\ITSupportPlatform\platform-core; $env:PORT='7019'; uv run python -m app.server`
  → `http://127.0.0.1:7019/docs`. **Cổng 7009 dành cho dịch vụ `PlatformCore`** — chạy thử dùng cổng khác (7019),
  xong nhớ tắt (chỉ dừng tiến trình có `app.server` trong dòng lệnh).
- Dịch vụ `PlatformCore` chạy từ `D:\ITSupportPlatformRun` (bản sao `main`), nhật ký `D:\ITSupportPlatformRun\logs\core-*.log`.
  Python của `.venv` là launcher (46 KB) gọi sang Python thật trong `%APPDATA%\uv\python\…` của tài khoản
  `anh.nguyennhuhoang` — LocalSystem đọc được; đừng xoá Python 3.14 đó bằng `uv python uninstall`.
  Khởi động lần đầu ≈ 13 s (biên dịch .pyc), ping Atlas lần đầu ≈ 0,5 s.
- Console máy chủ dùng cp1252: CLI phải gọi `utf8_stdio()`; script thử bằng Python thì đặt `PYTHONIOENCODING=utf-8`.
