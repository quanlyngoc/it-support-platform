# ADR-0012: Python 3.14 cho platform-core, dự phòng 3.13

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
3.13 sang giai đoạn chỉ vá bảo mật từ 10/2026; cần wheel gevent/greenlet ổn định.

## Quyết định
Dùng 3.14 nếu `gevent`, `greenlet` cài bằng wheel không phải biên dịch; nếu không, ghim 3.13 và ghi lại ở đây.

## Phương án đã loại
Giữ 3.12 của máy chủ hiện tại.

## Hệ quả
Python cài qua uv ở phạm vi người dùng, không đụng Python hệ thống.

## Kết quả kiểm 02/10/2026
Python 3.14.8: gevent 26.9, greenlet, pymongo, Flask 3.1, APIFlask 3.1.2, Flask-SocketIO 5.6.1 cài bằng wheel,
không biên dịch. Server chạy thật bằng gevent trên Atlas đạt → **chốt 3.14**, không cần dự phòng 3.13.
