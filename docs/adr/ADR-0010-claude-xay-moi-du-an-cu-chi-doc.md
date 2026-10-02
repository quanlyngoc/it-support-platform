# ADR-0010: Claude xây mới, dự án cũ chỉ đọc

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
Không được can thiệp cấu trúc mã nguồn của hệ đang chạy.

## Quyết định
Mã mới chỉ trong `D:\ITSupportPlatform`; thư mục cũ chỉ đọc, có rào kỹ thuật (deny + hook). Viết lại theo module, không chép nguyên khối.

## Phương án đã loại
Sửa dần hệ cũ.

## Hệ quả
Mỗi module cần bảng hành vi cũ ↔ mã mới ↔ test.
