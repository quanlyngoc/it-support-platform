# ADR-0002: Triển khai tại trường trước, cloud sau

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
Ngắt Internet chặn web máy trạm; WoL/VNC/giao-thu bài đi qua WAN nếu Core ở cloud; luật bảo vệ dữ liệu cá nhân 2025.

## Quyết định
On-prem với thiết kế sẵn đa tổ chức (tổ chức đầu tiên PHENIKAA); cloud và tổ chức thứ hai ở GĐ11.

## Phương án đã loại
Lên cloud ngay.

## Hệ quả
Cần VM tại trường; GĐ11 phải thêm relay tại trường và whitelist Core.
