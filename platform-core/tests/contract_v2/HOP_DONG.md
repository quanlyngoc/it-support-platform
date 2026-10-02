# Hợp đồng giao thức agent v2 (2.7.5.x) — đo từ mã nguồn ngày 02/10/2026

> Sổ tay bước 3.1. Nguồn đọc (CHỈ ĐỌC): `D:\NetworkInventory\app.py` (hub chạy `APP_ROLE=hub`, cổng 5009 sau Caddy :5443),
> `D:\NetworkInventory\agent_build\client.py` (`CLIENT_VERSION = "2.7.5.3"`). Số dòng ghi trong ngoặc là của hai tệp đó
> tại ngày đo. Mỗi mục có fixture trong `fixtures/` và test trong `test_contract_v2.py` (đang `xfail strict`,
> chuyển xanh ở bước 3.3 — khi test tự qua, pytest báo XPASS-strict → gỡ dấu `xfail` của mục đó).

## A. LUẬT SỐNG CÒN (§0 — giữ kết nối) — legacy_adapter PHẢI tuân thủ

| # | Luật | Vì sao (bằng chứng trong mã) |
|---|---|---|
| A1 | `POST /update` **luôn trả 200** (kể cả lỗi nội bộ của Core: nuốt lỗi, vẫn 200). Không bao giờ trả 426. | Agent chỉ coi `200`/`426` là "server sống" (client.py ~4147). Mã khác → `server_failed_count += 1`; đủ 3 lần → **săn server** (`server_hunter_loop`: IP nhớ trong Registry → UDP 5010 → DNS `phenikaa-server` → gương GitHub `server_ip.txt`) và có thể **chuyển hẳn sang IP khác**. |
| A2 | **Không** trả `{"action": "kill_and_update"}` / 426. | Hub cũ trả 426 khi agent cũ hơn `version.txt` (app.py ~2261). Agent 2.7.5.3 bỏ qua, nhưng agent đời cũ từng tự cập nhật bằng Popen+`os._exit` (đường đã làm sập fleet 3 lần). Cập nhật chỉ qua `/check_update` (có cổng chia đợt) hoặc lệnh `powershell` cài tách rời. |
| A3 | Có nhịp tim mà **không có socket** → trả `{"status":"success","action":"reconnect_socket"}`. Xét **TRƯỚC** mọi nhánh khác. | app.py ~2255 (bài học 08/09 + 13/09). Agent nhận thì `sio.disconnect()` rồi vòng 5 s tự nối lại; tự giới hạn 30 s/lần (client.py ~219). |
| A4 | `/check_update` mặc định trả **"không có bản mới"**: `{"version":"0.0.0.0","hash":"","size":0}`; chỉ máy nằm trong cổng chia đợt mới nhận bản thật. Luôn trả **200 + khoá `version`**. | Agent dùng chính endpoint này để **nhận diện "đúng server của ta"** khi săn server (`_looks_like_our_server`, ~287, `verify=False`). Thiếu `version` → agent coi Core là server lạ. |
| A5 | `/download_setup` chỉ phục vụ bộ cài **khớp `manifest.json` (SHA-256 + size)**; quá tải trả **503** (agent tự thử lại sau 5'). | client.py ~721-736: sai hash/size → bỏ qua, giữ agent cũ. Hub cũ: tối đa 60 lượt tải bắt đầu/45 s, slot tự hết hạn (bài học kẹt 503 44 phút). |
| A6 | **Không chạy bộ phản hồi UDP 5010** trên Core. | Hub cũ trả `PHENIKAA_DISCOVERY_PONG:5009`; hai bộ trả lời cùng lúc = agent có thể bám nhầm. Core đứng sau cùng Caddy/IP nên không cần. |
| A7 | Core phải đứng **sau đúng Caddy `:5443` với đúng chứng chỉ hiện tại**. | Agent ghim chứng chỉ `server.crt` đặt cạnh exe (`_VERIFY`, ~52) cho HTTP và cả WSS (`sslopt ca_certs`). Đổi cổng/chứng chỉ = mất kết nối. |
| A8 | Gửi lệnh: **không broadcast**. Máy có socket → `to='host_<HOSTNAME>'` + theo dõi ACK; máy **không có socket nhưng còn nhịp tim** → xếp vào hàng đợi HTTP `/check_command/<mac>`; máy tắt → báo "máy không còn kênh lệnh". | Hub cũ broadcast khi chưa `register` (app.py ~377) — trái luật cô lập tổ chức. Hàng đợi HTTP là đường dự phòng đã cứu A6-304-29 (bị chặn WebSocket). |
| A9 | Kết quả bất đồng bộ (`ps_bulk_result`, `send_report`, `collect_report`) lưu **MongoDB** theo token (TTL), không RAM; có API poll. | Hai tiến trình UI/HUB từng mất lệnh vì state trong RAM (luật §0.3). Bài học 18b: kết quả có thể về TRƯỚC khi trình duyệt nhận token. |
| A10 | Định danh phần cứng: bỏ serial rác (`N/A`, `...`, `unknown`, `default`, < 5 ký tự); trùng phần cứng → ghi `machine_events`, **không xoá máy**. | Bài học 10.20–10.21 (mất 5 máy phòng 404). Agent gửi `serial="N/A"` vài giây đầu sau khởi động (HW nạp ở luồng nền, ~4101). |

### A11. ⚠️ SỬA ĐIỀU KIỆN CANARY CỦA SỔ TAY 3.6 (không dùng User-Agent để tách agent)

Agent gửi **`User-Agent: Mozilla/5.0`** khi gọi `/check_update` và `/download_setup` (client.py 700, 716). Điều kiện
`not header User-Agent *Mozilla*` của Sổ tay 3.6 sẽ đẩy hai request đó về **hub cũ**, còn nhịp tim/lệnh về Core → máy
canary bị hai server cùng quản. Điều kiện đúng: **`client_ip` + danh sách đường dẫn của agent**:

```
@core_canary {
    client_ip 10.x.y.15/32
    path /update /check_update /download_setup /client_log /offline /check_command/* /login_result/*
    path /ps_auth_result/* /pty_auth_result/* /ps_bulk_result/* /send_report /collect_upload /collect_report
    path /work_file/* /fs_recv /fs_recv_raw /fs_serve/* /fs_bridge/* /socket.io/*
}
```
(Các dòng `path` trong cùng matcher được Caddy gộp kiểu HOẶC; cần xác nhận bằng `caddy adapt` ở bước 3.6.)
Trình duyệt trên chính máy canary mở trang IT Monitor cũ vẫn về UI cũ (đường dẫn `/`, `/room/...` không nằm trong danh sách);
chỉ `/socket.io/*` của trình duyệt đó lạc sang Core — chấp nhận được vì máy canary là máy sinh viên. Bước 3.2 (thu log thật)
phải xác nhận User-Agent của websocket-client khi mở `/socket.io/`.

## B. Thông số hành vi

| Thông số | Giá trị | Nguồn |
|---|---|---|
| Chu kỳ nhịp tim `POST /update` | ≈ 2 s/máy (`cpu_percent(interval=1)` + `sleep(1)`), timeout 5 s, Retry 3 lần cho 500/502/503/504 | client.py 4122-4161, 186 |
| Chu kỳ poll lệnh `GET /check_command/<mac>` | 1,6–3,0 s ngẫu nhiên, timeout 2 s; lỗi > 5 lần liên tiếp thì nghỉ thêm 5 s | 3914-3935 |
| Kiểm cập nhật `GET /check_update` | mỗi 60 s (luồng riêng), chống chạy đúp 300 s | 4126, 709 |
| Nối socket | `sio.connect(https://<ip>:5443, transports=['websocket'])`, thử lại mỗi 5 s; python-socketio 5.16 / engine.io 4 | 191-196 |
| Ngưỡng offline (hub cũ) | 35 s không nhịp tim (watchdog RAM 10 s/lần); socket rớt → offline NGAY | app.py 538-549, 482-492 |
| ACK lệnh | `ACK_TIMEOUT=8` s, `ACK_MAX_TRIES=3`, chỉ cho máy đã `register` | app.py 368-371, 433-445 |
| Chống chạy đúp ở agent | nhớ 500 `command_id` gần nhất | client.py 3705-3710 |
| Room socket | `host_<HOSTNAME viết hoa>` | app.py 447-453 |
| MAC | chữ thường, phân cách `:` (vd `aa:bb:cc:dd:ee:ff`) | client.py 3937-3950 |
| `disk_usage` | `"<ổ>:<tên ổ>:<%dùng>:<free_gb>:<total_gb>"` nối bằng `|`; lỗi → `"0"` | client.py 2039-2057 |
| Tải hiện tại (≈ 888 máy) | ≈ 440 nhịp tim/s + ≈ 400 poll lệnh/s | suy từ chu kỳ |

Hệ quả cho Core trên Atlas (RTT 55 ms): **không được chạm CSDL trong đường nhịp tim/poll lệnh**. Online + hàng đợi lệnh
giữ trong RAM của tiến trình duy nhất phục vụ agent; ghi `computers` gộp (khi đổi trạng thái hoặc 60 s/lần) ở luồng nền.

## C. HTTP do agent gọi

| Fixture | Route | Agent gửi | Hub cũ trả |
|---|---|---|---|
| `http_update_*.json` | `POST /update` | JSON nhịp tim (mục D) | xem A1–A3; thiếu `hostname` → 400 `{"status":"error"}` |
| `http_check_update_*.json` | `GET /check_update` (UA Mozilla) | — | `{"version","hash","size"}` (khoá `rollout` bị bỏ) |
| `http_download_setup.json` | `GET /download_setup` (UA Mozilla) | — | 200 tệp `Client_Management.exe` · 503 `busy` · 404 |
| `http_client_log.json` | `POST /client_log` | `{mac, hostname, context, error}` | `{"status":"success"}` |
| `http_offline.json` | `POST /offline` | `{hostname}` (gửi 1 lần khi máy bắt đầu tắt + atexit) | `{"status":"success"}`; đánh offline ngay + ghi mốc "tắt có chủ ý" cho hệ thi |
| `http_check_command_*.json` | `GET /check_command/<mac>` | — | `{"command": null}` · `{"command": "shutdown"\|"restart"\|"logout"}` · `{"command_obj": {...}}`; hàng đợi FIFO theo MAC |
| `http_login_result.json` | `POST /login_result/<mac hoặc hostname>` | `{status, msg?, hostname}` | `{"status":"ok"}` → phát `login_response` |
| `http_ps_auth_result.json` | `POST /ps_auth_result/<mac>` | `{status, msg?}` | `{"status":"ok"}` → `ps_auth_response` |
| `http_pty_auth_result.json` | `POST /pty_auth_result/<mac>` | `{status, msg?}` | `{"status":"ok"}` → `pty_auth_response` |
| `http_ps_bulk_result_*.json` | `POST /ps_bulk_result/<token>` | `{hostname, status: done\|error\|timeout, exit_code, stdout, stderr}` | `{"status":"ok"}`; token lạ → `{"status":"ignored"}` (vẫn 200) |
| `http_send_report.json` | `POST <report_url>` (mặc định `/send_report`) | `{session_id, hostname, status: ok\|partial\|fail, saved, skipped, failed, reason, files[{name, ok, error?, note?}]}` | `{"status":"ok"}` |
| `http_work_file.json` | `GET /work_file/<batch_id>/<tên có thể chứa />` | — | 200 tệp · 404 |
| `http_collect_upload.json` | `POST <upload_url>` (mặc định `/collect_upload`), multipart: `session_id`, `hostname`, `file=<host>.zip` | zip nén trong RAM | `{"status":"ok"}` · 404 phiên lạ · 400 thiếu tệp |
| `http_collect_report.json` | `POST /collect_report` | `{session_id, hostname, status: ok\|nofile\|nofolder\|fail, files[], deleted, error}` | `{"status":"ok"}` · 404 phiên lạ |
| `http_fs_recv_raw.json` | `POST /fs_recv_raw?token=&name=` (octet-stream, khối 256 KB) | luồng thô | `{"status":"ok"}` · 403 token sai |
| `http_fs_recv.json` | `POST /fs_recv` (multipart `token`, `file`) — agent đời cũ | | `{"status":"ok"}` · 403 · 400 |
| `http_fs_serve.json` | `GET /fs_serve/<tok>` (agent tải theo `download_url` trong `fs_request op=push`) | | 200 tệp · 403 · 404 |
| `http_fs_bridge.json` | `GET /fs_bridge/<tok>` | | 200 tệp · 403 · 404 `{"status":"pending"}` |

Ghi chú quan sát (cần xác nhận ở 3.2): `log_error()` gửi `/client_log` bằng `requests.post` **không** dùng `server.crt`
(client.py 178) → với chứng chỉ tự ký, đa số log lỗi có thể không bao giờ tới server; chỉ `_bao_dam_chay_duoi_system`
(dùng `http_session`) là chắc tới.

## D. Thân nhịp tim (`POST /update`, client.py 4133-4144)

`hostname, ip, mac, cpu, ram, mainboard, disk, model, serial, network, cpu_usage, ram_usage, disk_usage, cpu_temp,
cpu_fan, cmos_battery, client_version, dang_tat` — `dang_tat=1` là "máy sắp tắt" (đường báo thứ hai song song `/offline`).
Giá trị tạm lúc mới khởi động: `cpu/ram/mainboard/model/serial/disk/network = "N/A"` (luồng nền điền dần).
Xử lý phía hub cũ cần đọc thêm ở bước 3.3: `workers.py` `async_db_writer_worker` (ghi `computers`, ANTI-GHOST, `machine_events`,
cảnh báo RAM/ổ cứng → `incidents`), `usage_stats_worker` (+1 phút/máy online mỗi 60 s).

## E. Socket.IO

| Chiều | Sự kiện | Dữ liệu | Hành vi |
|---|---|---|---|
| agent→server | `connect` → `register` | `{hostname}` (giữ nguyên hoa/thường, server tự viết hoa) | join `host_<HOST>`, ghi `REGISTERED_HOSTS[HOST]=sid` |
| agent→server | `disconnect` | — | gỡ `REGISTERED_HOSTS`, đánh offline + phát `batch_device_update` ngay |
| agent→server | `cmd_ack` | `{command_id, hostname}` | bỏ khỏi danh sách chờ gửi lại |
| agent→server | `client_ps_output` | `{mac, data}` | chuyển `ps_output` tới trình duyệt (hub cũ broadcast; Core: tới đúng người mở phiên) |
| agent→server | `client_pty_output` | `{mac, data, closed?}` | `pty_output` tới room `ptyview_<mac bỏ dấu :>` |
| agent→server | `fs_progress` | `{req_id, reply_sid, sent, total, name}` | chuyển tới `reply_sid` |
| agent→server | `fs_response` | `{req_id, reply_sid, mac, op, ok, error, path?, items?, zipped?, name?}` | chuyển tới `reply_sid` |
| agent→server | `vnc_thumb` | `{hostname (HOA), image (base64 JPEG), hd, reply_sid}` | chuyển tới `reply_sid`; ảnh < 800 B coi như hỏng (frontend) |
| agent→server | `client_update` | thân nhịp tim (agent đời cũ) | xử lý như `/update`; 2.7.5.3 **không** còn gửi |
| server→agent | `execute_command` | `{command? \| command_obj?, command_id, mac, hostname}` | agent nhận nếu `hostname` khớp (không phân biệt hoa/thường) HOẶC `mac` khớp; ACK rồi chạy |
| server→agent | `server_ps_input` | `{mac, data}` | agent lọc theo MAC |
| server→agent | `server_pty_input` / `server_pty_resize` | `{mac?, hostname?, data}` / `{cols, rows, ...}` | gửi tới `host_<HOST>` |
| server→agent | `fs_request` | `{hostname, mac?, op, req_id, reply_sid, path/target/src/dst/name/token/folder/filename/unzip/download_url}` | `op`: `list, mkdir, delete, rename, pull, push, copy, recycle` |
| server→agent | `vnc_thumb_req` | `{hostname, reply_sid, hd}` | agent trả `vnc_thumb` (chỉ khi stream winvnc có khung < 15 s) |

## F. Lệnh (`execute_command` hoặc `/check_command`) — agent 2.7.5.3 (client.py 3280-3700)

| Dạng | Tên | Trường | Kết quả gửi về |
|---|---|---|---|
| `command` | `shutdown`, `restart` | — | `/offline` rồi `os._exit` |
| `command` | `logout` | — | — |
| `command_obj.action` | `relay_wake` | `target_mac, target_ip` | — (chỉ bắn khi cùng subnet) |
| | `relay_wake_batch` | `targets[{mac, ip}]` | — |
| | `receive_work` | `batch_id, files[], dest_folder, overwrite, session_id, report_url` | `report_url` (mục C) |
| | `collect_work` | `session_id, src_folder, patterns[], upload_url, delete_after` | `upload_url` + `/collect_report` |
| | `start_ps` / `stop_ps` | `user, pass` | `/ps_auth_result/<mac>` + `client_ps_output` |
| | `pty_validate` / `start_pty` / `stop_pty` | `user, pass` / `cols, rows` | `/pty_auth_result/<mac>` + `client_pty_output` |
| | `vnc_start` / `vnc_stop` | `relay_url, token, vnc_port?` | (tunnel tới relay `D:\RemoteControl`, giữ nguyên) |
| | `hsk_launch`, `show_sbd`, `hide_sbd` | `script, result_token, ...` | `/ps_bulk_result/<result_token>` khi thất bại |
| | `internet_control` | `sub_action: disable\|enable\|block_web\|unblock_web, websites` | — |
| | `powershell` | `script, user?, pass?, result_token?, timeout=90` | có `result_token` → `/ps_bulk_result/<token>`. **Có user/pass thì KHÔNG chạy SYSTEM** (bài học 10.22) |
| | `login_encrypted` | `data` = hex(nonce 12 B + AES-GCM ciphertext của `{"user","pass"}`), khoá = Registry `HKLM\SOFTWARE\PhenikaaIT\AesKey` | `/login_result/<mac>` |

Không còn trong 2.7.5.3 (CLAUDE.md cũ còn liệt kê): `kill_and_update`, `new/append/resolve/delete`.
Cập nhật agent an toàn hiện nay = `powershell` với script bootstrap của `/hubapi/push_update` (app.py 6023-6084):
cài bằng tác vụ Task Scheduler tách rời, báo tiến độ qua `/ps_bulk_result/<token>`; máy mất socket thì đi hàng đợi HTTP.

## G. Phụ thuộc ngoài agent (không thuộc 3.3 nhưng phải giữ khi chuyển phòng)

- Hệ thi (ThiHSK/ThiPM) gọi hub qua `/internal/*` + `/hubapi/*` (`X-Internal-Token`) — phòng chuyển sang Core thì hệ thi phải
  hỏi Core cho máy của phòng đó (GĐ9, xem `D:\ExaminationSystem\CLAUDE_THI.md`). Mốc "tắt có chủ ý" (`TAT_SACH`) cũng phải có ở Core.
- Relay VNC (`PhenikaaVncRelay`, cổng 6080 qua Caddy `@vncws`) giữ nguyên; Core chỉ phát `vnc_start {relay_url, token}`.

## H. Ánh xạ hành vi cũ ↔ mã mới ↔ test (bước 3.3, 02/10/2026)

| Hành vi hub cũ (CHỈ ĐỌC) | Mã Core (`app/legacy_adapter/`) | Test |
|---|---|---|
| `/update` `_ingest_heartbeat` + `reconnect_socket` (app.py 2212-2263) | `fastpath.py` → `adapter.handle_update` → `state.ingest` | `http_update_*`, `test_a1_*`, `test_a3_*` |
| `/check_command` `COMMAND_QUEUE` FIFO (4260) | `fastpath.py` → `adapter.handle_check_command` → `state.pop_command` | `http_check_command_*`, `test_a8_*` |
| `dispatch_command` + `_ack_retry_loop` (408-445) | `adapter.dispatch` / `retry_tick` + `state.track`/`due_retries` | `sock_out_execute_command`, `test_ack_*` |
| `register` / `disconnect` / `cmd_ack` (447-498) | `socket_handlers.py` | `sock_in_register|disconnect|cmd_ack` |
| `ram_watchdog_worker` 35 s (538) | `state.sweep` (gọi trong `writer.tick`) | `test_mat_nhip_tim_35s_*` |
| `async_db_writer_worker` + `_mevt_swap`/`_mevt_hwid` (workers.py 41-249) | `writer.py` | `test_trao_phan_cung_*`, `test_anti_ghost_*`, `test_cung_ten_doi_*` |
| `usage_stats_worker` (551) | `writer._usage` | `test_phut_su_dung_*` |
| `/check_update` + `/download_setup` cổng chia đợt (1871-2011, 2182) | `update_gate.py` + `http_routes.py` | `http_check_update_*`, `test_cong_*`, `test_tai_bo_cai_*` |
| `ps_bulk_result`/`send_report`/`collect_*` RAM (4474, 4925-5031) | `store.py` (MongoDB) + `http_routes.py` | `http_ps_bulk_*`, `http_send_report`, `http_collect_*`, `test_api_powershell_*` |
| `FS_TOK`/`FS_PULL`/`FS_PUSH` RAM (697-717, 1395-1456) | `store.py` (`file_metadata` scope `fs_token`) | `http_fs_*` |
| `client_ps_output`/`client_pty_output`/`fs_*`/`vnc_thumb` (650-816) | `socket_handlers.py` | `sock_in_*` |
| `/offline` + `TAT_SACH` (4556-4580) | `http_routes.offline` + `state.tat_sach` | `http_offline`, `test_lenh_tat_*` |

**Cố ý KHÁC hub cũ (đừng "sửa lại cho giống"):**
1. Không broadcast ở bất kỳ đâu (hub cũ broadcast khi chưa `register`, `server_ps_input`, `ps_output`, `*_auth_response`,
   `login_response`, `pty_output` thiếu MAC).
2. Thiếu `hostname` ở `/update` → 200 `{"status":"error"}` (hub cũ 400) — luật A1.
3. Không bao giờ 426 dù agent cũ hơn `version.txt` — luật A2.
4. Hàng đợi HTTP có hạn 5 phút; ACK hết lượt không chuyển sang hàng đợi HTTP (đường HTTP của agent không chống đúp).
5. `/check_update` chỉ mời cập nhật khi bộ cài KHỚP manifest; hub cũ trả version kể cả khi thiếu manifest.
6. Giá trị tạm `N/A`/`...` không đè thông tin phần cứng thật; ghi `computers` gộp (đổi trạng thái + 60 s) thay vì mỗi nhịp.
7. Kết quả bất đồng bộ + token truyền tệp lưu MongoDB (hub cũ để RAM).
8. Cổng chia đợt cộng dồn kiểu HOẶC (`all` / máy / phòng / %); hub cũ: có danh sách phòng thì bỏ qua %.

Chưa làm trong 3.3 (ghi để không quên): cảnh báo đổi RAM/ổ cứng → `incidents` (`check_hardware_changes`, GĐ incidents);
Desktop tham gia room `t:<tid>:{ps|pty|watch}` qua socket có xác thực (GĐ4); API cấp phiên giao/thu bài + token
truyền tệp cho Desktop (GĐ7); `/internal/*` + `/hubapi/*` cho hệ thi (GĐ9); dọn tệp cũ trong `<DATA_DIR>`.
