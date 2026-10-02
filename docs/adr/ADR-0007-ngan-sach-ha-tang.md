# ADR-0007: Ngân sách hạ tầng

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
Cần cụm CSDL, máy Core, lưu tệp, ký số.

## Quyết định
3 VM MongoDB + 1 VM Core (+ dự phòng), ổ lưu tệp, chứng thư ký mã OV/EV.

## Phương án đã loại
Dùng chung máy chủ Windows Server 2019 hiện tại (hết hỗ trợ mở rộng 09/01/2029).

## Hệ quả
Chi phí ban đầu cao hơn; tách bạch rủi ro với hệ đang chạy.
