# ITSupportPlatform — Phenikaa IT Monitor 3.0 (SaaS đa tổ chức)

Nền tảng mới thay cho IT Monitor 2.x, xây mới hoàn toàn theo phương án đã duyệt ngày 02/10/2026.
Hệ đang chạy (`D:\NetworkInventory`, `D:\ExaminationSystem`, `D:\Agent`, `D:\Caddy`, `D:\RemoteControl`)
**chỉ được đọc**, không sửa (xem `CLAUDE.md` §0 luật 14 và `.claude/hooks/guard_readonly.py`).

| Thư mục | Vai | Công nghệ |
|---|---|---|
| `platform-core/` | Backend trung tâm (API, realtime, tổ chức, phân quyền, dữ liệu) | Python 3.14 · Flask/APIFlask · Flask-SocketIO + gevent · PyMongo · MongoDB 8.0 |
| `platform-agent/` | Agent Windows, phần mềm `.exe` cài trên máy trạm | Python + Nuitka → `Client_Manager.exe` · bộ cài Inno Setup 6.7 |
| `desktop-app/` | Ứng dụng quản trị cho máy IT/giảng viên | Tauri 2 + React 19 + Vite 8 + TypeScript |
| `platform-master/` | Tổ chức, giấy phép, phiên bản, cập nhật | Python · MongoDB `itm_master` |
| `platform-deployment/` | Build, bộ cài, dịch vụ, cổng QA | uv · pnpm · Nuitka · Inno Setup · NSSM · Caddy |
| `docs/` | ADR, phương án, sổ tay thực hiện | — |

Bắt đầu đọc: `CLAUDE.md` → `docs/plan/` (Phương án + Sổ tay) → `docs/adr/`.

## Chạy kiểm tra (platform-core)

```powershell
cd D:\ITSupportPlatform\platform-core
uv sync
uv run ruff check .
uv run pytest -q
```
