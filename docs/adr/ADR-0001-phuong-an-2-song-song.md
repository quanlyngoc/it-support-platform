# ADR-0001: Phương án 2: xây song song, chuyển từng phòng

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
Đặc tả V2 không có chiến lược chuyển 889 máy đang chạy; viết lại rồi chuyển một lần vi phạm §0 (luật 5, 6).

## Quyết định
Xây nền tảng mới song song; Core có bộ tương thích agent cũ; chuyển từng phòng bằng định tuyến Caddy theo dải IP; đổi server trước, agent sau.

## Phương án đã loại
PA1 viết lại chuyển một lần (rủi ro mất kết nối quá cao); PA3 tiến hoá tại chỗ (không đạt mục tiêu Desktop/MongoDB/đa tổ chức).

## Hệ quả
Thêm khoảng 10–15% công cho bộ tương thích và thời gian chạy song song; đổi lại quay lui chỉ bằng cấu hình.
