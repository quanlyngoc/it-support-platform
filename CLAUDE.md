# ITSupportPlatform — Phenikaa IT Monitor 3.0 (nền tảng SaaS đa tổ chức)

> **CLAUDE.md của repo mới `D:\ITSupportPlatform`.** Đặt ở gốc repo từ ngày đầu Giai đoạn 2. Nền tảng được Claude
> **xây mới hoàn toàn** tại đây. CLAUDE.md của hệ cũ (`D:\NetworkInventory`) giữ nguyên, không sửa, vẫn là tài liệu
> của hệ đang chạy cho tới khi hệ cũ được lưu trữ.
> Toàn bộ trao đổi trong dự án **bằng tiếng Việt**.

---

## 0. ⛔ ĐIỀU KIỆN TỐI THƯỢNG — KHÔNG ĐƯỢC LÀM MẤT KẾT NỐI CORE ↔ AGENT

Giữ nguyên 8 luật của hệ cũ (fail-safe update · installer không là tiến trình con · state chung ra DB ·
route ra lệnh phải qua đúng cổng · canary 2-3 máy trước · cấm bật toàn fleet khi cơ chế cài chưa chứng minh ·
Task Scheduler `PhenikaaITMonitor` + watchdog `PhenikaaITMonitorWD` luôn tồn tại · nút dừng khẩn All Update).
Bổ sung cho nền tảng mới:

9.  **Không có truy vấn tenant-owned nào thiếu `tenant_id`.** Mọi truy cập dữ liệu đi qua `TenantRepo`;
    `tenant_id` lấy từ phiên đã xác thực (`g.ctx`), KHÔNG BAO GIỜ từ body/header/query do client gửi.
10. **Giao thức agent cũ (v2) là hợp đồng bất biến** cho tới khi 100% máy chạy agent v3 ≥ 4 tuần.
    Sửa `legacy_adapter` phải chạy bộ kiểm thử hợp đồng v2 (`platform-core/tests/contract_v2`) trước khi phát hành.
11. **Không xoay chứng thư TLS của Caddy cổng 5443** khi còn agent v2 (agent v2 ghim chứng thư).
12. **Lệnh gửi agent luôn có `expires_at`.** Lệnh hết hạn agent bỏ qua (chống chạy lại lệnh tắt máy
    sau khi mất mạng rồi nối lại).
13. **Mọi đợt thay đổi ảnh hưởng máy trạm** (agent, Caddy, Internet Control, chứng thư) theo thứ tự:
    1 máy → 1 phòng → nhiều phòng → toàn trường, mỗi bước có **cổng kiểm thử** + **lệnh quay lui đã diễn tập**.
14. **Dự án cũ CHỈ ĐỌC.** `D:\NetworkInventory`, `D:\ExaminationSystem`, `D:\Agent`, `D:\Caddy`, `D:\RemoteControl`:
    Claude được đọc để hiểu hành vi, **không sửa, không tạo, không xoá** tệp ở đó. Mã mới chỉ nằm trong `D:\ITSupportPlatform`.
    Thao tác vận hành trên máy chủ (Caddyfile, dịch vụ NSSM, cài đặt cần quyền Administrator) do người vận hành làm theo Sổ tay.

---

## 1. Tổng quan

| Hạng mục | Chi tiết |
|---|---|
| Mô hình | Modular monolith, đa tổ chức (multi-tenant) dùng chung CSDL, phân tách bằng `tenant_id` |
| Thành phần (đúng tên đặc tả §4.1) | `platform-core` · `platform-agent` · `desktop-app` · `platform-master` · `platform-deployment` |
| Core | Python 3.14 (dự phòng 3.13) · Flask 3.1 + APIFlask (OpenAPI) · Flask-SocketIO 5.6 + gevent · PyMongo 4 (đồng bộ, hợp gevent) · Pydantic v2 |
| CSDL | MongoDB 8.0, replica set 3 node, `w=majority`; DB `itm_core` (Core) và `itm_master` (Master) TÁCH RIÊNG. **Giai đoạn dựng thử: MongoDB Atlas** (8.0.34, RTT ≈ 55 ms — ADR-0013); chạy thật: cụm `rs0` 3 VM tại trường (ADR-0004). Chuỗi kết nối chỉ ở `platform-core/.env` |
| Desktop | **Tauri 2 + React 19 + Vite 8 + TypeScript** (ứng dụng một trang, mẫu chính thức của Tauri) · React Router 7 (hash router) · TanStack Query · socket.io-client · xterm.js · noVNC · Chart.js |
| Agent | **Phần mềm .exe**: `Client_Manager.exe` (Python biên dịch bằng Nuitka 4.x, máy trạm không cần Python) + bộ cài `PhenikaaITMonitor-Agent-Setup-<ver>.exe` (Inno Setup 6.7, cài im lặng, nâng cấp tại chỗ); chạy bằng Task Scheduler quyền SYSTEM |
| Cách xây dựng | Claude xây mới hoàn toàn trong `D:\ITSupportPlatform`; dự án cũ chỉ đọc (mục 13) |
| Reverse proxy | Caddy 2.11 (dịch vụ `CaddyServer`): `:5443` agent v2 + legacy; `:7443` Desktop + agent v3 |
| Cổng nội bộ | Core `7009` · Master `7010` · MongoDB `27017` (chỉ mở giữa các node + Core) |
| Dịch vụ Core (dựng thử) | NSSM `PlatformCore`, chạy từ bản sao **`D:\ITSupportPlatformRun`** (nhánh `main`, KHÔNG phải thư mục phát triển), nghe `127.0.0.1:7009`; quản lý bằng `platform-deployment\nssm\dich_vu_core.ps1` |
| Tổ chức đầu tiên | `PHENIKAA` (on-prem tại trường). Tổ chức khác chỉ mở khi GĐ11 hoàn tất |

**IP thật của client** nằm ở `X-Forwarded-For` (Core đứng sau Caddy) → chỉ dùng helper `client_ip()`.

---

## 2. Cấu trúc monorepo `D:\ITSupportPlatform` (5 project theo đặc tả §4.1)

```
platform-core/        app/{api,auth,tenants,users,rbac,rooms,devices,agents,commands,realtime,
                      legacy_adapter,incidents,chat,work,files,reports,audit,settings,
                      integrations/{ldap,smtp,telegram,gemini,hsk_thipm},workers,storage,
                      db/{client,indexes,validators,seeds,migrations},security,config,utils}
                      tests/{unit,isolation,contract_v2,contract_v3} · pyproject.toml · uv.lock
platform-agent/       agent/ (mã mới theo module: transport_v2, transport_v3, identity, heartbeat, hwinfo,
                      commands/, ps, pty, fs, vnc, wfp, login, work, update) · tests/ · build/ (Nuitka,
                      PhenikaaITMonitor-Agent.iss, watchdog.ps1) · dist/ (Client_Manager.exe, Setup .exe)
desktop-app/          index.html · vite.config.ts · src/ (React + Vite: authentication, dashboard, rooms, devices,
                      remote, terminal, file-manager, work, chat, incidents, reports, settings, admin,
                      api-client, realtime-client, tenant-context, session, shared) · src-tauri/
platform-master/      app/... (tenant lifecycle, license, activation, version, support token)
platform-deployment/  caddy/ · nssm/ · build/ · updater/ · qa/ (check_routes.py, check_eol.py) · runner/
docs/adr/             Quyết định kiến trúc (ADR-0001...)
```

| File | Line ending | BOM |
|---|---|---|
| `*.py`, `*.ts(x)`, `*.json`, `*.toml`, `*.md` | LF | không |
| `*.bat`, `*.cmd`, `*.iss` | **CRLF** | không |
| `*.ps1` | CRLF | **có** (PowerShell 5.1 đọc UTF-8 cần BOM) |

Ghim trong `.gitattributes`; kiểm bằng `platform-deployment/qa/check_eol.py` (mục 11).
CLI/server in tiếng Việt phải gọi `app.utils.console.utf8_stdio()` trước (console máy chủ là cp1252 → `UnicodeEncodeError`).

---

## 3. Quy trình làm việc BẮT BUỘC

1. Đọc file thật trước khi sửa; sửa từng khối, không viết lại cả file.
2. Mọi API mới khai báo đủ 8 mục: xác thực · tenant · quyền · sở hữu tài nguyên · validate đầu vào ·
   hành động · audit · response (Pydantic schema → OpenAPI).
3. Thêm field/collection: theo đúng 7 bước §76 của đặc tả — cập nhật `app/db/validators.py` + `app/db/indexes.py`
   + API contract + test cô lập tenant. Schema chuẩn là chương 4A (đặc tả V3).
4. Sau khi sửa chạy cổng QA (mục 11). Thất bại = không merge.
5. Cập nhật CLAUDE.md + ADR khi đổi quy ước.
6. Không thêm microservice, Redis, message queue (đặc tả cấm). Cần phát sự kiện giữa nhiều instance Core
   thì dùng MongoDB change streams.

---

## 4. Tổ chức (tenant), xác thực, phân quyền

- Đăng nhập Desktop: **Mã tổ chức + tài khoản + mật khẩu** (+ TOTP nếu bật). Desktop nhớ mã tổ chức lần trước.
- Phiên: token ngẫu nhiên 256-bit, DB chỉ lưu **SHA-256 của token** (`sessions.session_token_hash`). Quyền, `is_super`,
  `room_ids` được **chụp vào phiên lúc đăng nhập**; `auth.service.resolve()` đệm RAM 15 giây (Atlas chậm) → khoá tài
  khoản/treo tổ chức/đá thiết bị có hiệu lực chậm tối đa 15 giây. Test cần thấy ngay thì gọi `clear_cache()`.
- Một thiết bị/một thời điểm: `active_sessions` unique `(tenant_id, user_id)`; đăng nhập mới thay phiên cũ.
  Super Admin miễn trừ.
- Giới hạn IP theo từng tài khoản (`allowed_ip_cidrs`; rỗng = mọi nơi). Nghiêm ngặt: bật mà IP không khớp → chặn.
- Mật khẩu: **Argon2id**. Secret cấu hình (SMTP, LDAP bind, Telegram, Gemini): AES-256-GCM, khoá chính ngoài DB.
- RBAC: `permissions` (catalog toàn nền tảng) → `policies` (theo tổ chức, có `room_ids`) → user/AD user.
  Policy `Super Admin` là system policy, không sửa/xoá.
- `g.ctx = {tenant_id, user_id, permissions, room_ids, is_super, system}` gắn trong `before_request`.
- **Truy cập dữ liệu tenant-owned CHỈ qua `TenantRepo`** (`app/tenants/repo.py`; collection bất kỳ: `repo_for(db, tid, col)`).
  Repo tự gắn `tenant_id`, chặn truy vấn/ghi mang `tenant_id` khác, chặn `$lookup/$unionWith/$out/$merge`, chặn
  `delete_many({})`. Test `tests/isolation/test_no_raw_queries.py` quét mã: `db["computers"]`/`db.users`… ngoài
  `repo.py` và `app/db/` là đỏ.
- **Kiểm tham chiếu trước khi ghi (4A.29):** `require_refs(db, tid, rooms=..., computers=[...])` (`app/tenants/refs.py`)
  → `RefNotFound` (route đổi thành 404, không lộ tài nguyên tổ chức khác). Policy chỉ gắn quyền có thật:
  `app/rbac/catalog.py` + `app/rbac/service.create_policy`.
- Socket.IO `/desktop`: xác thực bằng token lúc `connect`, join room `t:<tenant>:u:<user>` và `t:<tenant>:room:<room>`.
- **Hệ thi (HSK/ThiPM) dùng hệ tài khoản riêng** (admin.db của ExaminationSystem). Core KHÔNG lưu tài khoản thi.

---

## 5. Giao tiếp Core ↔ Agent

### Hai giao thức chạy song song
| | Agent v2 (2.7.5.x) — `legacy_adapter` | Agent v3 (3.x) |
|---|---|---|
| Vào qua | Caddy `:5443`, đường dẫn cũ (`/update`, `/check_update`, `/socket.io/*`…) | Caddy `:7443`, namespace `/agent`, chỉ websocket |
| Định danh | hostname (+ MAC) → device thuộc tenant `PHENIKAA` | `agent_id` (GUID sinh khi enroll) + khoá Ed25519 |
| Lệnh | `execute_command` như cũ | Envelope v3 có `command_id`, `expires_at`, `sig` (Ed25519 của Core) |
| Định tuyến | room `host_<HOSTNAME>` | room `t:<tenant>:dev:<device_id>` |

- **Hợp đồng v2 đầy đủ (đo từ mã 2.7.5.3): `platform-core/tests/contract_v2/HOP_DONG.md`** — đọc mục A (luật sống còn)
  TRƯỚC khi sửa bất cứ gì trong `legacy_adapter`. Ba luật dễ phạm nhất: `/update` **luôn 200, không bao giờ 426**
  (mã khác ×3 → agent đi "săn server"); `/check_update` luôn 200 + khoá `version` (agent dùng nó để nhận ra server);
  Core **không** trả lời UDP 5010.
- **Mã `app/legacy_adapter/`** (bước 3.3 xong 02/10/2026): `state.py` (RAM: online, socket, hàng đợi HTTP, ACK — thuần,
  không Flask) · `adapter.py` (ghép + `dispatch` + vòng nền) · `fastpath.py` (đường nhanh WSGI cho `/update` +
  `/check_command`, ≈ 95% lưu lượng — KHÔNG đi qua Flask) · `http_routes.py` (16 route còn lại) · `socket_handlers.py` ·
  `writer.py` (ghi `computers` theo lô) · `store.py` (MongoDB `command_results`/`file_metadata` + tệp đĩa) ·
  `update_gate.py` · `identity.py` · `api.py` (`/api/legacy/*` cho Desktop/vận hành) · `contract.py` (bộ chạy test hợp đồng).
- **KHÔNG BAO GIỜ broadcast lệnh.** Máy có socket → room `host_<HOST>` + ACK; còn nhịp tim mà mất socket → hàng đợi HTTP
  `/check_command/<mac>` (lệnh quá **5 phút** bị bỏ — máy bật lại không chạy `shutdown` cũ); máy tắt → kênh `none` →
  API trả 409. Kể cả `server_ps_input` (hub cũ broadcast) nay tra MAC → máy rồi gửi trúng đích.
- ACK: `command_id`, `ACK_TIMEOUT=8s`, `ACK_MAX_TRIES=3`. Hết lượt/mất socket → **bỏ cuộc, KHÔNG chuyển sang hàng đợi
  HTTP**: đường `/check_command` của agent KHÔNG chống chạy đúp theo `command_id` (client.py 3922-3931) → chuyển là có
  thể chạy lệnh 2 lần.
- Kết quả bất đồng bộ lưu MongoDB `command_results` (TTL 2 ngày) + phát socket room `t:<tenant_id>:res:<token>` + poll
  `GET /api/legacy/results/<token>`. Room phía Desktop luôn mang mã tổ chức: `t:<tid>:{ps|pty|watch}:<mac12>`,
  `t:<tid>:devices` (sự kiện `legacy_devices` mỗi 2 s).
- Online: RAM `LegacyState`; bộ ghi nền (2 s/nhịp) ghi `computers` khi đổi trạng thái + định kỳ 60 s/máy (tối đa 60
  máy/nhịp, giãn đều), `usage_stats` +1 phút/máy/60 s. KHÔNG ghi Mongo mỗi nhịp tim. Không bao giờ xoá máy; tráo phần
  cứng → `machine_events` + `computers_archive`. Giá trị tạm `N/A`/`...` không đè dữ liệu thật.
- Cổng cập nhật: `settings` `update.all|hosts|rollout_rooms|rollout_percent` (mặc định tắt hết) + bộ cài phải khớp
  `manifest.json`; kho bộ cài `<DATA_DIR>/<MÃ>/updates/`. Kho tệp khác: `<DATA_DIR>/<MÃ>/{work,collect,fs_tmp}`.
- Nhật ký: `geventwebsocket.handler` ghi MỌI request ở INFO (bỏ qua `log_output`) → `app/server.py` hạ về WARNING;
  quên là ≈ 10 GB/ngày. Tóm tắt `SYNC` 1 dòng/60 s.
- `engineio.payload.Payload.max_decode_packets = 500` (bài học View desktop).
- Agent v3 mất kênh mới 10 phút liên tục → tự rơi về kênh v2 (Core vẫn phục vụ) → không bao giờ mồ côi.

### Action agent xử lý
`powershell` · `start_ps`/`stop_ps` · `start_pty`/`stop_pty`/`pty_validate` · `login_encrypted` ·
`internet_control` · `relay_wake`/`relay_wake_batch` · `receive_work` · `collect_work` ·
`hsk_launch` · `show_sbd`/`hide_sbd` · `vnc_start`/`vnc_stop` + lệnh chuỗi `shutdown`/`restart`/`logout`;
sự kiện riêng `vnc_thumb_req`, `fs_request`. (`kill_and_update` KHÔNG còn trong agent 2.7.5.3 — Core không được gửi.)

---

## 6. Desktop App

- **React + Vite, ứng dụng một trang** (tạo từ `pnpm create tauri-app`, mẫu React + TypeScript). Build ra `dist/`;
  dev server cổng `1420` (`strictPort`); `tauri.conf.json`: `devUrl` = `http://localhost:1420`, `frontendDist` = `../dist`.
- Router dùng `createHashRouter` (đường dẫn `#/…`) để tải lại cửa sổ không lỗi. Mọi logic nghiệp vụ ở Core.
- Kiểu dữ liệu API sinh tự động từ OpenAPI của Core (`openapi-typescript` + `openapi-fetch`).
- Realtime: `socket.io-client` namespace `/desktop`; mất kết nối → banner đỏ + tự nối lại + đồng bộ lại số tuyệt đối.
- **Số liệu online luôn GHI ĐÈ số tuyệt đối** từ server (`room_stats`, `total_online`), cấm cộng dồn.
- Payload máy offline không có CPU/RAM/Disk → mọi chỗ vẽ chỉ số bọc `if (is_online)`.
- Thông báo chat: Tauri notification plugin → thông báo hệ điều hành thật (nháy taskbar).
- Tự cập nhật: Tauri updater (chữ ký Ed25519/minisign); khoá riêng nằm trong kho bí mật, KHÔNG trong repo.
- Phiên bản đang chạy: menu Trợ giúp → Giới thiệu (thay cho `FB_VER`/`CHATBOX_VER` của web cũ).

---

## 7. Tích hợp hệ thi (ThiHSK / ThiPM — `D:\ExaminationSystem`)

- Giữ nguyên hợp đồng `/internal/*` (`ping`, `machines`, `dispatch`, `track/*`, `upload_work`, `thu/*`, `collect/*`).
- Xác thực: on-prem giữ `X-Internal-Token` + chỉ localhost/allowlist; khi lên cloud chuyển sang API key theo
  tổ chức (`X-ITM-Key-Id` + HMAC-SHA256 `X-ITM-Signature` + `X-ITM-Timestamp` ±300s).
- `/internal/machines` trả cờ `online` (nhịp tim) và `nhan_lenh` (có socket) — hai thứ KHÁC NHAU.

---

## 8. Lưu trữ tệp

- `StorageService` (giao diện chung): `LocalFS` (on-prem, `D:\ITSupportPlatformData`) hoặc `S3` (SeaweedFS / dịch vụ S3 trong nước).
  KHÔNG dùng MinIO (đã ngừng bảo trì, archive 25/04/2026).
- Khoá lưu trữ luôn có ranh giới tổ chức: `tenants/<tenant_id>/{work,collected,thu,chat,report,temp}/...`.
- MongoDB chỉ giữ metadata (`file_metadata`); tệp lớn truyền dạng luồng, không nạp cả tệp vào RAM.
- Dọn tự động: `temp` 48h, `work` 48h, `collected` 168h (worker đọc `file_metadata.expires_at`).

---

## 9. MongoDB — collection chính (DB `itm_core`)

Tenant-owned (bắt buộc `tenant_id`): `users` · `ad_user_policies` · `policies` · `rooms` (kèm `map`, `live_layout`) ·
`computers` · `agents` · `agent_enrollments` · `incidents` · `usage_stats` · `online_state` · `client_logs` ·
`sessions` · `active_sessions` · `settings` · `chat_messages` (`scope` LAB/HSK) · `chat_reads` · `chat_reactions` ·
`audit_log` (`system` LAB/HSK/THI) · `pushed_files` · `file_metadata` · `machine_events` · `computers_archive`.

Platform-owned: `tenants` · `permissions` (Core) · `platform_licenses` · `platform_activations` ·
`platform_versions` · `support_tokens` (DB `itm_master`).

Quy tắc then chốt:
- `computers`: định danh = `agent_id`; `mac`, `serial`, `hostname` là thuộc tính, index KHÔNG unique.
  Phát hiện trùng phần cứng → ghi `machine_events` + chép `computers_archive`, **KHÔNG BAO GIỜ tự xoá máy**.
- Placeholder dữ liệu phần cứng của agent phải là giá trị server coi là rác (`N/A`); server bỏ qua serial < 5 ký tự.
- TTL: `sessions.expires_at`, `agent_enrollments.expires_at`, `client_logs` 90 ngày, `audit_log` 180 ngày.
  `machine_events` bất biến, không TTL.
- Validator `$jsonSchema` ở mức `moderate` cho mọi collection; đổi schema = cập nhật `app/db/validators.py`.

---

## 10. Bài học bắt buộc giữ (mang từ hệ cũ)

1. gevent: chỉ dùng thư viện I/O thuần Python (PyMongo ổn); cấm gọi C-extension chặn lâu trong greenlet.
2. Không tự gộp/xoá máy dựa trên serial/MAC (mất 5 máy phòng 404 ngày 16/09).
3. Mật khẩu VNC: bất biến 4 chỗ (Core · agent · `ultravnc.ini` của bộ cài · script vá) — giá trị nằm trong kho bí mật.
4. `passwd2` (chỉ-xem) không bao giờ trùng `passwd`; `ForceCursorShape=0`; giết sạch `winvnc.exe` trước khi sửa ini.
5. Thumbnail màn hình lấy từ winvnc qua RFB trong agent (không chụp bằng PowerShell — AMSI chặn).
6. Hai file exe: `Client_Management.exe` = bộ cài, `Client_Manager.exe` = agent. Không đổi tên.
7. Phát hành agent 2 giai đoạn: staging → verify → manifest (SHA-256 + size) → version CUỐI CÙNG.
8. Không tin `errorlevel` của `nssm start`; luôn đọc `nssm status` thật.
9. Kết quả bất đồng bộ gắn token: đệm kết quả về sớm + poll dự phòng.
10. "Dịch vụ đang chạy/cổng đang mở" ≠ "cấu hình đúng": tự chữa phải kiểm thứ quan trọng (vd. xác thực thật).

---

## 11. Cổng QA trước khi phát hành

```powershell
cd D:\ITSupportPlatform\platform-core
uv run ruff check .
uv run pyright
uv run pytest -q                  # mongomock: unit + tests/isolation (23 mục §4A.36/§77) (+ contract_v2/v3 từ GĐ3)
uv run pytest -q -m atlas         # CSDL thật: database tạm itm_test_<ngẫu nhiên>, tự xoá
uv run pytest -q -o addopts="" ..\platform-deployment\qa          # test hook chỉ-đọc + test công cụ QA
uv run python ..\platform-deployment\qa\check_routes.py           # trùng route/endpoint/socket
uv run python ..\platform-deployment\qa\check_eol.py              # line ending + BOM toàn repo
pnpm -C desktop-app typecheck; pnpm -C desktop-app lint; pnpm -C desktop-app test
pnpm -C desktop-app tauri build                    # chỉ khi phát hành Desktop
```

Phát hành agent: build → ký số → canary 2-3 máy ≥ 10 phút (quay lại online đúng version) → 1 phòng → nhiều phòng → All Update.

---

## 11b. Đóng gói agent thành phần mềm .exe

- `Client_Manager.exe`: Nuitka `--standalone --windows-console-mode=disable`, có icon, `--file-version`, company/product name; ký số.
- Bộ cài `PhenikaaITMonitor-Agent-Setup-<ver>.exe` (Inno Setup 6.7): `AppId=Phenikaa IT Inventory` (bằng giá trị ngầm định
  của bộ cài cũ), `DefaultDirName={autopf}\PhenikaaIT`, `PrivilegesRequired=admin`; giữ tên task `PhenikaaITMonitor`
  (onstart, SYSTEM) + `PhenikaaITMonitorWD` (1 phút) → **cài đè tại chỗ lên agent 2.7.5.x, không để lại hai bản**.
- Tham số: `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SERVER=<địa chỉ> /ENROLL=<mã> /LOG="C:\ProgramData\PhenikaaIT\install.log"`;
  `/SERVER`, `/ENROLL` đọc bằng hằng `{param:...}` và ghi vào `C:\ProgramData\PhenikaaIT\agent.json`.
- Bước cuối bộ cài: chạy task và **kiểm `Client_Manager.exe` đang chạy**. Gỡ: `unins000.exe /VERYSILENT` (giữ `agent_id`).
- Cập nhật cho máy đang có agent luôn qua Core + cài bằng task tách rời (luật §0.2), không gọi bộ cài như tiến trình con.

## 12. Git & CI

- Repo private `phenikaa-platform`; nhánh `main` được bảo vệ, mọi thay đổi qua Pull Request + CI xanh.
- Bí mật KHÔNG vào repo: `.env` đặt ở `D:\ITSupportPlatformSecrets\`; pre-commit `gitleaks` chặn khoá/mật khẩu.
- CI: GitHub Actions, runner tự host Windows cho build Nuitka/Tauri + ký số.
- Commit của Claude gắn dòng `Co-Authored-By` cuối message; tránh `reset --hard`, `push --force`.

---

## 13. Mô hình xây dựng: Claude xây mới, dự án cũ chỉ đọc

| Nguồn chỉ đọc | Đọc để lấy |
|---|---|
| `D:\NetworkInventory\CLAUDE.md` | Luật §0, bài học 10.x |
| `app.py`, `utils.py`, `workers.py`, `config.py` | Hành vi 152 route + 16 socket, hợp đồng agent v2 |
| `templates\*.html`, `fbrowser.js`, `chatbox.js`, `collectlog.js` | Hành vi giao diện cần giữ khi viết lại bằng React |
| `agent_build\client.py`, `TaoApp.iss`, `build_client.bat`, `publish_release.ps1`, `watchdog.ps1` | Hành vi agent 2.7.5.3, đóng gói, cài đặt |
| `D:\ExaminationSystem\CLAUDE_THI.md`, `KE_HOACH_TACH_DOC_LAP.md` | Hợp đồng `/internal/*`, biến `MONITOR_*` |

- Claude Code mở tại `D:\ITSupportPlatform`. `.claude/settings.json` đã khai sẵn thư mục cũ để đọc (`additionalDirectories`),
  luật `deny` Edit cho thư mục cũ, và hook `PreToolUse` **`.claude/hooks/guard_readonly.py`** chặn mọi lệnh ghi/sửa/xoá
  vào thư mục cũ (kể cả qua shell). Test của hook: `platform-deployment/qa/test_guard_readonly.py`. **Không gỡ hook này.**
- **Viết lại, không chép nguyên khối.** Mỗi module có bảng "hành vi cũ ↔ mã mới ↔ test"; agent có bảng tương đương 2.7.5.3 ↔ 3.0.
- Claude không chạy lệnh cần quyền Administrator (cài dịch vụ, sửa Caddy, tường lửa): ghi rõ lệnh để người vận hành chạy.
- Hết mỗi phiên: `git -C D:\NetworkInventory status` không có thay đổi mới do phiên đó.

---

## 14. Tiến độ (cập nhật mỗi khi xong một bước của Sổ tay)

| Ngày | Giai đoạn / bước | Trạng thái | Ghi chú |
|---|---|---|---|
| 02/10/2026 | Phê duyệt phương án | Xong | Thư mục gốc đổi từ `D:\Platform` thành `D:\ITSupportPlatform` |
| 02/10/2026 | 0.11 Không gian xây mới + rào chỉ đọc | Xong | `.claude/settings.json` + hook `guard_readonly.py` (có test) |
| 02/10/2026 | 2.2 Khung 5 project, `.gitattributes`, `.gitignore`, ADR | Xong | `docs/adr/ADR-0001…0012` |
| 02/10/2026 | 2.3–2.10 Nền platform-core | Xong (trừ CI chạy thật) | Atlas `itm_core` đã khởi tạo; tổ chức PHENIKAA + `admin`; 58 test + 3 test Atlas xanh; ruff/pyright sạch; CI viết sẵn, chờ repo GitHub |
| 02/10/2026 | 2.11 Core thành dịch vụ NSSM | Xong | Người vận hành cài tay theo lệnh nssm; dịch vụ `PlatformCore` Running, Delayed Auto, LocalSystem, nghe `127.0.0.1:7009`, ping Atlas ≈ 0,4 s, giết tiến trình → tự lên lại. Quản lý: `platform-deployment/nssm/dich_vu_core.ps1` (KiemTra không cần Admin; CapNhat/Go cần Admin) |
| 02/10/2026 | 3.1 Hợp đồng agent v2 | Xong | `tests/contract_v2/HOP_DONG.md` + 45 fixture (xfail strict chờ 3.3). Phát hiện: agent gửi UA `Mozilla/5.0` ở `/check_update`/`/download_setup` → sửa điều kiện canary 3.6 (mục A11) |
| 02/10/2026 | 3.3 legacy_adapter | Xong (chờ thử tải 30 phút) | 45/45 test hợp đồng xanh; 133 test; đường nhanh WSGI: 300 agent ≈ 5% một lõi, p99 ≈ 3 ms. Dịch vụ `PlatformCore` cần `dich_vu_core.ps1 -Lenh CapNhat` để chạy mã này |
| — | 3.4 Cập nhật agent từ Core · 3.2/3.5–3.9 Caddy canary | Kế tiếp | 3.4 phần mã đã có trong `update_gate.py`; còn chép bộ cài + kiểm |

Chi tiết bàn giao từng bước: `docs/TIEN_DO.md`.

Việc cần người vận hành (Claude không có quyền Administrator): GĐ1 (MongoDB replica set, VM, tường lửa, sao lưu),
đẩy mã lên GitHub (`git push`), cài Node.js/Rust/VS Build Tools cho desktop-app (GĐ4), `dich_vu_core.ps1 -Lenh CapNhat`
khi cần đưa mã mới lên dịch vụ `PlatformCore`, sửa Caddyfile.
