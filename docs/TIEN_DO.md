# Sổ bàn giao tiến độ — ITSupportPlatform

> **Phiên Claude mới: đọc tệp này ngay sau `CLAUDE.md`, rồi làm tiếp từ mục "BƯỚC TIẾP THEO".**
> Mỗi khi xong một bước: cập nhật tệp này + bảng mục 14 của `CLAUDE.md` TRƯỚC khi sang bước khác,
> để nếu phiên bị dừng giữa chừng thì phiên sau vẫn biết chính xác đang ở đâu.
> Kế hoạch đầy đủ: `docs/plan/SoTay_ThucHien_ITMonitor_SaaS.html` (số bước bên dưới theo Sổ tay;
> tài liệu đó còn ghi `D:\Platform` — hiểu là `D:\ITSupportPlatform`).

Cập nhật lần cuối: 04/10/2026 (GĐ4 4.1–4.6 xong, 4.7 chờ cổng :7443; GĐ5 5.1–5.3 + 5.5 xong; kế: 5.4 View desktop + VNC)

## Cách mở phiên mới để làm tiếp

1. Mở VS Code tại `D:\ITSupportPlatform` → mở Claude Code (CLAUDE.md và `.claude/settings.json` tự nạp).
2. Gõ: **"Đọc CLAUDE.md và docs/TIEN_DO.md rồi làm tiếp BƯỚC TIẾP THEO."**
3. Muốn mở lại đúng cuộc trò chuyện cũ: trong Claude Code gõ `/resume` (hoặc chạy `claude --continue` ở thư mục đã làm việc).
4. Kiểm nhanh trạng thái trước khi làm tiếp (tất cả phải xanh):
   ```powershell
   cd D:\ITSupportPlatform\platform-core
   uv run pytest -q                 # 177 passed, 1 skipped (05b chờ GĐ7 tải tệp)
   uv run ruff check .
   uv run pyright
   pnpm -C ..\desktop-app typecheck; pnpm -C ..\desktop-app build   # PATH cần C:\Program Files\nodejs + %APPDATA%\npm
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
| 2.8 | `/api/auth/login` · `logout` · `me`: Local (Argon2id), AD (LDAP), TOTP, 1 thiết bị, giới hạn IP, sai mã tổ chức | `tests/unit/test_auth_api.py` |
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
| 5.1 + 5.5 (phần Core) | `app/devices/` + `app/rooms/` + `app/reports/config_export.py`: `GET /api/rooms` · `/api/rooms/{id}` · `/api/rooms/move-targets` · `GET /api/devices` (`room_id`, `q`, `online`) · `/api/devices/{id}` · `POST /api/devices/{id}/move` · `/api/devices/move-bulk` · `DELETE /api/devices/{id}` (lưu `computers_archive` trước) · `GET /api/devices/events` (chỉ đọc) · `GET /api/reports/config-export` (Excel 3 sheet như hệ cũ). Mỗi tên phòng có tài liệu `rooms` (bộ ghi tự tạo) → `computers.room_id`; hàm phân giải phòng duy nhất `writer.room_of` tôn trọng phòng ép, tự gỡ khi tên máy đã đúng vị trí; xoá máy dọn phòng ép. Phạm vi phòng theo policy (`ctx.room_ids`). Realtime `batch_device_update` tới `t:<tid>:room:<id>` (+ bảng tổng `t:<tid>:devices`) luôn kèm `room_stats` + `total_online` tuyệt đối (chỉ phòng chính thức); máy offline không kèm CPU/RAM/Disk. Quyền mới `device.manage` (đã seed lên `itm_core`) | 9 test API mới (154 xanh) + Atlas: `upserted_ids` → `device_id` ngay cho máy mới. Desktop (5.2–5.4) chờ GĐ4. Cần `CapNhat` |
| 3.3 (bổ sung) | Thay đổi phần cứng → sự cố (`hardware.py`, `writer._hardware`): THÊM/MẤT/TRÁO ĐỔI RAM, Ổ CỨNG, HẾT PIN CMOS theo đúng quy tắc hệ cũ; so trong RAM (nạp nền từ CSDL lúc khởi động), chỉ chạm CSDL khi có thay đổi; chống trùng sự cố đang chờ; phát `incident_new` tới `t:<tid>:incidents`. Dọn tệp cũ (`cleanup.py`, 6 giờ/lần): work/fs_tmp 48 giờ, collect 168 giờ, CHỈ mục tên mã phiên, không đụng `updates/` | 12 test mới (145 xanh) + Atlas: validator `incidents` nhận tài liệu sự cố. Chưa gửi email/Telegram cho sự cố (GĐ8). Cần `CapNhat` để dịch vụ chạy |
| 0.6 + 0.7 | **Đã cài** (người vận hành chạy `cai_dat_ops.ps1 -Lenh CaiDat`, 03/10/2026 00:15–00:20) | Sao lưu `database_20261003.db` 29 MB / 889 máy + `may_20261003.csv`; tin thử Telegram gửi được (script dừng ngay nếu lỗi, đã qua bước sau đó); baseline có dòng mỗi phút (00:16 → nay), hub_loi 0; kho bí mật đã khoá (tài khoản thường bị từ chối). `KiemTra` bằng tài khoản thường suy trạng thái từ độ mới của baseline/bản sao vì không xem được tác vụ SYSTEM |
| 4.1 + 4.2 | Công cụ máy phát triển (người vận hành cài, Claude kiểm 03/10/2026): Node.js **v24.15.0**, Rust **1.99.0** (MSVC), VS 2022 Build Tools có MSVC + Windows SDK, WebView2 154. pnpm **12.8.1** cài mức người dùng (`npm i -g pnpm` → `%APPDATA%\npm`, kho gói `D:\.pnpm-store`) — không cần Administrator | `node -v`, `rustc -V`, `pnpm -v` |
| 4.3 + 4.5 | `desktop-app/` từ mẫu Tauri 2 React-TS: React 19, Vite 8, TS 6, react-router 8 (`createHashRouter` — F5 không lỗi), TanStack Query 5, zustand, plugin `store` (phiên lưu bằng Tauri store, chạy trình duyệt thì `sessionStorage`). `src/api-client`: **kiểu sinh từ OpenAPI của Core** (`pnpm gen:api` = `app.openapi_dump` trên mongomock → `openapi-typescript`, kết quả tất định — CI sinh lại rồi `git diff --exit-code`). `src/realtime-client`: socket.io namespace `/desktop`, chỉ websocket, `auth:{token}`, `request()` có ack 8 s. `tauri.conf.json`: productName/identifier/cửa sổ 1440×900 (min 1280×720)/CSP/NSIS theo Sổ tay 4.4 | `pnpm typecheck` + `pnpm build` (408 KB JS) đạt; `cargo build` bản debug đạt (7 ph 25 s, BelowNormal 2 job). Job `desktop` thêm vào CI |
| 4.5 (phía Core) | `app/api/cors.py` (CORS cho `/api/*` + `/openapi.json`, header Bearer, không credentials; `ALLOWED_ORIGINS="*"` = `HOAN_BAO_MAT`) · `app/openapi_dump.py` · **namespace `/desktop`** (`app/realtime/desktop.py`): bắt buộc token, kiểm lại token MỖI sự kiện (đăng xuất / bị đá phiên / khoá → ngắt ngay), room luôn mang mã tổ chức, `subscribe_room` theo phạm vi phòng của policy, `subscribe_result`/`watch_device`/`pty_*`/`ps_input`/`fs_request` cần `device.control`, `vnc_thumb_req` cần `remote.vnc`; `reply_sid` do server gắn. `legacy_adapter` phát cho Desktop CHỈ qua `/desktop` (agent ở `/` không nghe được) | 7 test `test_desktop_socket.py` + CORS/openapi trong `test_auth_api.py` (164 xanh). **Cần `CapNhat`** |
| 4.6 (bản đầu) | Màn Đăng nhập (mã tổ chức nhớ lần trước, TOTP hiện khi Core trả `TOTP_REQUIRED`, ô máy chủ ẩn trong "Máy chủ"), thanh trên hiện tổ chức + người dùng, dải đỏ "MẤT KẾT NỐI" + nối lại thì tải lại số tuyệt đối. Dashboard: tổng/online/offline/số phòng, thẻ theo phòng (Phòng chờ tách riêng), số online GHI ĐÈ từ `room_stats`. Trang phòng: bảng máy, CPU/RAM realtime, máy offline bỏ số đo | Chạy thử đầu-cuối (Core 7019 + DB tạm `itm_uitest` + 6 máy giả + vite + Chrome headless): đăng nhập → Dashboard 5/5 online, Phòng chờ riêng → trang phòng 3 máy → F5 giữ đúng trang + phiên, không hiện dải đỏ. DB tạm đã xoá |
| 4.4 | Plugin `updater` (`requireSignedVersion: true`, `pubkey`, endpoint `https://10.21.24.142:7443/desktop/latest.json`, NSIS `passive`) + `notification` + `process` (quyền trong `capabilities/`). Khoá ký sinh bằng `tauri signer generate` ở `%USERPROFILE%\.tauri\itmonitor.key` + mật khẩu ngẫu nhiên trong `itmonitor.key.password.txt` (không in ra, ngoài repo — `HOAN_BAO_MAT`) | `pnpm tauri build` (scratchpad `tauri_build_thap.ps1`, BelowNormal 2 job, 550 s): `Phenikaa IT Monitor_0.1.0_x64-setup.exe` 2,35 MB + `.sig`; trusted comment ghi `version:0.1.0`. Updater dùng reqwest 0.13 + `rustls-platform-verifier` → tin kho chứng chỉ Windows (giống WebView2) |
| 4.6 | Core: `GET /api/incidents` (`status` = OPEN / PENDING / PROCESSING / DONE, `q`, `limit`) + `GET /api/incidents/summary` (số tuyệt đối: đang mở / chờ / đang xử lý / cảnh báo phần cứng đang mở), lọc phạm vi phòng theo `room_name` của các phòng trong policy. Desktop: thẻ "Phiếu sự cố đang mở" + "Cảnh báo phần cứng", đồng hồ, biểu đồ Chart.js online/offline theo phòng, bảng 8 sự cố đang mở mới nhất; `incident_new` → tải lại số + thông báo HĐH khi cửa sổ không được xem; trang **Giới thiệu** (`#/about`) phiên bản ứng dụng + Core + realtime + nút kiểm tra cập nhật; dải "Có bản mới — Cập nhật và mở lại" | 4 test mới (168 xanh). Chạy thử đầu-cuối: thẻ 1 phiếu / 1 cảnh báo, biểu đồ 1333×198, bảng sự cố đúng, Giới thiệu: Core 3.0.0-dev, "Đang kết nối", 19 quyền. Dashboard khớp số máy canary: chờ 3.5–3.8 |
| 4.7 (phần mã) | Core `GET /desktop/latest.json` (204 khi chưa có bản nào → updater coi là "không có bản mới") + `/desktop/<tên>.exe` + `.sig` (chỉ đúng mẫu tên, không cần đăng nhập — an toàn nhờ chữ ký), kho `<DATA_DIR>/desktop/`. `platform-deployment/desktop/phat_hanh_desktop.py`: kiểm phiên bản trong chữ ký, chép bộ cài + `.sig` (ghi tạm → đổi tên), ghi `latest.json` CUỐI, giữ bản vừa phát hành + 2 bản lớn nhất; `--notes-file` cho ghi chú có dấu. Khối Caddy `platform-deployment/caddy/khoi_7443.caddy` | 2 test Core + 4 test QA (27 xanh). Chạy thật: phát hành bộ cài 0.1.0 vào kho tạm → Core 7019 trả `latest.json` (no-store) + bộ cài tải về trùng SHA-256. `caddy adapt` bản sao Caddyfile + khối mới → 3 server `:5443/:5444/:7443`. Bắt được lỗi: dọn bản cũ từng xoá đúng bộ cài `latest.json` đang trỏ khi phát hành bản hạ cấp |
| — | Người vận hành `CapNhat` (03/10/2026 10:20) | `KiemTra`: bản `77f0c1e` = main, ping CSDL 55 ms; trên dịch vụ: `/desktop/latest.json` 204, `/api/incidents/summary` + `/api/rooms` 401 khi chưa đăng nhập, CORS trả đúng origin `http://tauri.localhost`. 3 traceback trong `core-err.log` là của 02/10 (11:20Z, 11:21Z, 17:32Z — trước khi có bản chặn `d2aaaa8`); lần dừng 10:20 hôm nay không sinh traceback |
| 5.2 | Desktop: trang **Phòng máy** (`#/rooms`, tìm theo tên); **chi tiết phòng**: máy sắp theo số ghế (GV cuối, nhãn GV như `_isGV` cũ), trạng thái + kênh lệnh, CPU/RAM/ổ đĩa theo giây (thanh đo ngưỡng cũ > 50 vàng / > 90 đỏ, tách `disk_usage` như `scripts.html`), IP·MAC, Model·Service tag, agent, số sự cố đang mở; lọc "chỉ online" + tìm; chọn nhiều máy → **Chuyển phòng** hàng loạt; Chuyển / Xoá từng máy với **hộp xác nhận** (máy đang online → cảnh báo sẽ tự thêm lại). **Chi tiết máy** (`#/devices/:id`): số đo realtime, cấu hình đầy đủ (CMOS hết pin tô đỏ), sự cố của máy, nhật ký thay đổi máy (quyền `machine_events.view`). Nút theo quyền `device.manage`. Core: `/api/incidents` thêm lọc `hostname` (đúng tên) + `room_id` | 168 test Core xanh. Chạy thử đầu-cuối (scratchpad `e2e_rooms.py`, 7 máy giả có `disk_usage`): thứ tự 01,02,03,GV; ổ C 61% vàng / D 91% đỏ; CPU đổi theo giây (88% → 94%); chi tiết máy đủ cấu hình + sự cố; Chuyển 1 máy kèm vị trí 9 → nhãn "chuyển tay · 9"; chọn 2 máy → chuyển cùng lúc (không có ô vị trí) → máy về đúng phòng theo tên tự gỡ nhãn; Xoá máy online → có cảnh báo, bản ghi vào `computers_archive` |
| 5.3 (Core) | `app/rooms/maps.py`: sơ đồ CÓ CẤU TRÚC trong `rooms.map` (máy · bàn GV · cửa 1–4 · bảng · đồ vật y tế/PCCC/kệ giày/tủ đồ/tủ rack · bàn SV · phần tử lạ giữ nguyên HTML; hướng `dir-*`; cụm có tên; mã thiết bị / màn hình / case), toạ độ cùng hệ px với trình vẽ cũ. Đọc tệp sơ đồ cũ (ẢNH CHỤP DOM của `room_detail.html` captureState: `bounds`/`items[].html`/`pcClasses`/`canvasWidth`) và **xuất lại đúng định dạng đó** (`to_legacy`). API `GET/PUT/DELETE /api/rooms/<id>/map` · `POST …/map/import-excel` (multipart, trả sơ đồ mới CHƯA lưu) · `POST …/map/export-excel`; quyền `room_map.edit` + phạm vi phòng; lưu → ghi tệp NGUYÊN TỬ vào `MAPS_EXPORT_DIR` (mặc định `<DATA_DIR>/<MÃ>/Maps`) cho `MONITOR_MAPS_DIR` của hệ thi, xuất lỗi vẫn lưu + báo; chưa có trong Core → đọc kho cũ `LEGACY_MAPS_DIR` (CHỈ ĐỌC, mặc định `D:\NetworkInventory\Maps` nếu có); realtime `room_map_updated`. Excel: quy tắc `renderGrid` cũ (85×95, cặp bàn 20, giữa bàn 80, hàng 22, gốc 90; 1 chữ số thêm 0) + bảng mã thiết bị. `maps_cli nhap-cu` / `xuat` | 9 test (177 xanh). **19/19 sơ đồ thật** đọc → xuất → đọc ổn định. **Chạy CHÍNH `sodo.js` của hệ thi** (Chrome headless, scratchpad `sodo_that.py`): HTML sơ đồ vẽ từ tệp gốc và từ tệp Core xuất **giống hệt** ở 19/19 phòng. Test bắt 2 lỗi: dọn nhầm cột trống khi xuất Excel; cửa mặc định CSS bị đọc thành y=0 |
| 5.3 (Desktop) | Trang phòng có 2 kiểu xem **Danh sách / Sơ đồ** (nhớ trong phiên). Sơ đồ: thẻ máy tô theo trạng thái thật (xanh online · vàng chỉ HTTP · mờ offline · viền đứt = chữ trên thẻ không khớp máy nào, khớp như `mapFindHost` của hệ thi), tooltip CPU/RAM, bấm → chi tiết máy, Ctrl+bấm → chọn máy để Chuyển phòng (dùng chung thanh chọn), danh sách "máy chưa có trên sơ đồ"; phóng/thu (Ctrl+lăn chuột). **Trình sửa** (`room_map.edit`): kéo 1/nhiều phần tử hít lưới cũ (Alt = tự do), khoanh vùng / Ctrl+bấm chọn nhiều, đổi cỡ phần tử + viền phòng, cửa chỉ trượt dọc tường, thêm máy theo số ghế / bàn GV / bảng / bàn SV / đồ vật, xoay hướng, gom/bỏ cụm có tên, xoá, hoàn tác/làm lại 50 bước (Ctrl+Z/Y), phím mũi tên, nhập/xuất Excel, Lưu (báo lỗi xuất cho hệ thi nếu có) / Huỷ (hỏi nếu chưa lưu); người khác lưu cùng lúc → báo; phòng chưa có sơ đồ → "Tạo từ danh sách máy" / "Sơ đồ trống" | Chạy thử đầu-cuối (scratchpad `e2e_map.py`, sơ đồ phòng 301 THẬT đọc từ kho cũ): 48 máy + 4 cửa + GV, 6 máy có nhịp tim sáng đúng; kéo chuột máy 01: 810 → 735 (đúng mốc lưới); Ctrl+Z → 810, làm lại → 735; gom cụm "Nhóm thi A"; Lưu → tệp `Phòng_301_-_A6.json` trong kho xuất có `l=735px` + cụm; Ctrl+bấm máy 04 → thanh "Đã chọn 1 máy". Sửa 2 lỗi thấy qua ảnh chụp: tỉ lệ "vừa khung" không chạy (ResizeObserver gắn lúc đang tải), cửa tường trái bị cắt |
| 3.1 | Hợp đồng agent v2: `platform-core/tests/contract_v2/HOP_DONG.md` (luật sống còn A1–A11, thông số, 18 route HTTP, 15 sự kiện socket, 15 action lệnh) + 45 fixture + `test_contract_v2.py` | 3 test kiểm fixture xanh; 45 test hợp đồng `xfail strict` chờ 3.3 |

## Đang làm

- (không có)

## BƯỚC TIẾP THEO

1. ~~Cài 0.6 + 0.7~~ — xong 03/10/2026.
2. Theo dõi baseline vài ngày (`D:\Backup\baseline\online_<ngày>.csv`) để biết ngưỡng cảnh báo có gây báo động giả giờ tan
   học không (Sổ tay 0.8 dùng chính số liệu này).
3. **Canary 1 máy (3.5 → 3.8)** theo Sổ tay đã sửa: chọn máy thử không dạy, người trực có mặt; ghi tên máy vào
   `D:\Backup\baseline\canary_hosts.txt` TRƯỚC khi sửa Caddy (để 0.7 không báo máy đó "rớt"); khối Caddy ở 3.6 đã kiểm sẵn.
4. Phần còn lại ghi ở `HOP_DONG.md` mục H "Chưa làm": gửi email/Telegram cho sự cố (GĐ8); API phiên giao/thu bài + token
   truyền tệp cho Desktop (GĐ7); `/internal/*` cho hệ thi (GĐ9). (Desktop vào room có xác thực: XONG — namespace `/desktop`.)
5. **4.7 thử thật** (sau khi người vận hành mở `:7443` — mục dưới): cài bản 0.1.0 trên 2 máy quản trị (bộ cài ở
   `desktop-app\src-tauri\target\release\bundle\nsis\`), đăng nhập qua `https://10.21.24.142:7443` → tăng `version` lên 0.1.1
   (`tauri.conf.json` + `package.json` + `Cargo.toml`), build lại, `phat_hanh_desktop.py --data-dir D:\ITSupportPlatformData`
   → ứng dụng 0.1.0 báo bản mới → cập nhật → mở lại ở 0.1.1. Sửa 1 ký tự trong `signature` của `latest.json` → ứng dụng
   PHẢI từ chối. (Dịch vụ đã `CapNhat` lên `77f0c1e` lúc 10:20 03/10 — `/desktop/latest.json` trả 204.)
6. **5.4 View desktop + VNC** (lưới card theo `{fx,fy}` mirror sơ đồ, khung HD khi rê chuột, noVNC cửa sổ con,
   `rooms.live_layout`; relay `D:\RemoteControl` + bất biến mật khẩu VNC 4 chỗ — bài học 10.22–10.24 hệ cũ). Đọc kỹ
   `room_detail.html` (View desktop) + `client.py` (`_rfb_stream_loop`, `do_vnc_thumb`) + relay TRƯỚC khi viết.
7. 5.3 còn lại khi CHUYỂN HẲN (không làm lúc chạy song song): `maps_cli nhap-cu --tenant PHENIKAA` → `maps_cli xuat` → trỏ
   `MONITOR_MAPS_DIR` của ThiHSK/ThiPM sang `D:\ITSupportPlatformData\PHENIKAA\Maps` (người vận hành, dịch vụ hệ thi).
   **Chưa nhập sớm có chủ ý:** trong lúc song song quản trị vẫn sửa sơ đồ ở hệ cũ; Core chưa có bản riêng thì luôn hiện bản
   MỚI NHẤT của hệ cũ, nhập sớm thì Core giữ một bản chụp đứng yên. Hệ thi đọc kho của chính nó trước, kho cũ sau — không
   đổi gì cho tới lúc chuyển.
   Core: thêm schema `@output` để kiểu response cũng sinh tự động (hiện viết tay ở `desktop-app/src/api-client/types.ts`).

## Việc cần người vận hành (Claude không có quyền Administrator)

- [ ] Đẩy mã lần đầu: remote `origin` = github.com/quanlyngoc/it-support-platform đã đặt; người vận hành chạy
      `git push -u origin main` → CI tự chạy (kiểm lại phiên bản `actions/checkout`, `astral-sh/setup-uv` mới nhất).
- [x] 2.11: dịch vụ `PlatformCore` đã cài (02/10/2026). Khi có mã mới cần chạy trên dịch vụ: PowerShell **Run as Administrator** →
      `Set-ExecutionPolicy -Scope Process Bypass -Force; & D:\ITSupportPlatform\platform-deployment\nssm\dich_vu_core.ps1 -Lenh CapNhat`
      (máy chủ thiếu System32 trong PATH nên KHÔNG gõ `powershell -File ...`; Claude không tự làm được vì cần dừng dịch vụ).
- [x] `dich_vu_core.ps1 -Lenh CapNhat` — dịch vụ chạy mã 3.3 (02/10/2026 18:20).
- [x] Bước 0.6, 0.7: đã cài 03/10/2026 (`ops\cai_dat_ops.ps1 -Lenh KiemTra` để xem).
- [ ] 3.5–3.9: canary bằng Caddy — chỉ làm sau khi 0.6 + 0.7 chạy và có người trực (3.2 không còn bắt buộc).
- [x] Cài Node.js 24 LTS, Rust, VS Build Tools trên máy phát triển desktop-app (GĐ4) — Claude kiểm đủ 03/10/2026.
- [x] `dich_vu_core.ps1 -Lenh CapNhat` lên `77f0c1e` (03/10/2026 10:20). Mã 5.2 (lọc sự cố theo máy/phòng) + 5.3 (API sơ
      đồ, kho xuất `D:\ITSupportPlatformData\PHENIKAA\Maps`) cần `CapNhat` lần kế — không gấp, chưa máy nào gửi về Core.
      Sau `CapNhat` dịch vụ tự đọc sơ đồ cũ ở `D:\NetworkInventory\Maps` (CHỈ ĐỌC — không cần đặt biến môi trường).
- [ ] 4.7 — mở cổng Desktop (PowerShell **Run as Administrator** trên máy chủ, làm theo phần đầu tệp
      `platform-deployment\caddy\khoi_7443.caddy`): chép khối vào CUỐI `D:\Caddy\Caddyfile` → `caddy validate` → `caddy reload`
      (nạp nóng, không đụng `:5443/:5444`) → mở tường lửa TCP 7443. Trên **2 máy quản trị** thử: `Import-Certificate` tệp
      `server.crt` vào `Cert:\LocalMachine\Root`. Kiểm: trình duyệt máy quản trị mở `https://10.21.24.142:7443/api/health` không
      báo lỗi chứng chỉ.

## Hoãn bảo mật (làm ở giai đoạn hoàn thiện, trước khi chạy thật)

- [ ] Atlas: đổi mật khẩu `admin` (đã xuất hiện trong khung chat), tạo user riêng `core_app` (readWrite `itm_core`),
      `master_app` (readWrite `itm_master`); giới hạn Network Access theo IP công khai của máy chủ.
- [ ] Đổi mật khẩu tài khoản `admin` của tổ chức PHENIKAA (đang là mật khẩu dựng thử trong `.env`).
- [ ] Đặt `MASTER_KEY_B64` riêng (đang dùng khoá dev mặc định trong `app/config/settings.py`); `ALLOWED_ORIGINS` theo Desktop.
- [ ] Rà mọi nhãn `HOAN_BAO_MAT` trong mã (`rg HOAN_BAO_MAT D:\ITSupportPlatform`).
- [ ] Khoá ký cập nhật Desktop: hiện ở `%USERPROFILE%\.tauri\itmonitor.key` + mật khẩu ngẫu nhiên ghi CẠNH khoá
      (`itmonitor.key.password.txt`). Khi hoàn thiện: tạo khoá mới, mật khẩu do người vận hành gõ tay, cất khoá vào kho bí mật
      + sao lưu ngoại tuyến, đổi `pubkey` trong `tauri.conf.json` (bản đã cài thử phải cài lại tay — không tự cập nhật sang khoá mới).
- [ ] Chứng chỉ `:5443/:7443` (`D:\NetworkInventory\certs\server.crt`) là CA:TRUE không giới hạn tên: máy nào tin nó thì người
      giữ `server.key` giả được MỌI trang web trên máy đó. Khi hoàn thiện: CA riêng có Name Constraints (chỉ IP máy chủ) hoặc
      chứng chỉ thật cho tên miền; chỉ cài lên máy quản trị cần dùng Desktop.
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
- **Desktop khi phát triển:** PATH phải có `C:\Program Files\nodejs` + `%APPDATA%\npm` (pnpm). Chạy giao diện trong trình
  duyệt: Core cổng 7019 + `pnpm -C desktop-app dev` → `http://localhost:1420` (vite nghe `localhost` = `::1`), ô "Máy chủ"
  ở màn đăng nhập đổi thành `http://127.0.0.1:7019`. **Build Rust (`pnpm tauri dev/build`, `cargo build`) rất nặng — máy chủ
  đang phục vụ hệ cũ** nên luôn chạy ưu tiên thấp + 2 job (scratchpad `cargo_build_thap.ps1`: `CARGO_BUILD_JOBS=2`, tiến
  trình BelowNormal); lần đầu ≈ 7,5 phút, sau đó chỉ biên dịch lại phần đổi. Chạy thử đầu-cuối: scratchpad `e2e_desktop.py`.
- Desktop gọi Core qua `http://127.0.0.1:7009` chỉ được trên chính máy chủ; máy quản trị khác cần `https://10.21.24.142:7443`
  (Caddy; chứng chỉ hiện có chỉ cấp cho IP, nên KHÔNG dùng tên miền; Windows phải tin chứng chỉ — WebView2 và updater đều đọc
  kho chứng chỉ Windows).
- Chạy thử Desktop đầu-cuối: scratchpad `e2e_seed.py init|incident|drop` (DB tạm `itm_uitest`) + `e2e_desktop.py` (tự gọi
  seed, chụp `e2e_*.png`, xoá DB ở cuối). Thử kho phát hành: `e2e_release.py` (Core 7019, `DATA_DIR` = kho tạm `rel_data`).
- Launcher `.venv\Scripts\python.exe` của uv làm mất dấu tiếng Việt trong tham số dòng lệnh (thành `?`) — Python thật thì
  không. CLI nhận chữ có dấu phải cho đường vào qua tệp UTF-8 (vd `phat_hanh_desktop.py --notes-file`).
