# ADR-0005: Đăng nhập bằng mã tổ chức + tài khoản + mật khẩu

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
Đặc tả §7.3 yêu cầu chốt cách nhận diện tổ chức trước khi viết xác thực.

## Quyết định
Ô Mã tổ chức (Desktop nhớ lần trước) + tài khoản + mật khẩu (+ TOTP nếu bật). Tổ chức lấy từ phiên, không nhận header/tham số tổ chức từ client.

## Phương án đã loại
Tên miền theo tổ chức.

## Hệ quả
Mỗi tổ chức có mã duy nhất `tenants.code`.
