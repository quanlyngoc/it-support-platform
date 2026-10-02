# ADR-0009: Agent là phần mềm .exe có bộ cài

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
Máy trạm phải cài được agent bằng một tệp; agent mới phải thay agent cũ không để lại hai bản.

## Quyết định
`Client_Manager.exe` (Nuitka) + bộ cài `PhenikaaITMonitor-Agent-Setup-<ver>.exe` (Inno Setup 6.7) giữ `AppId=Phenikaa IT Inventory`, `{autopf}\PhenikaaIT`, task `PhenikaaITMonitor`/`PhenikaaITMonitorWD`; cài im lặng `/VERYSILENT`.

## Phương án đã loại
Viết agent bằng ngôn ngữ khác.

## Hệ quả
Cần chứng thư ký mã; bảng tương đương chức năng với 2.7.5.3.
