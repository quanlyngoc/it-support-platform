"""Đối tượng Socket.IO dùng chung. Đặt riêng ở đây (không ở app.server) để khi chạy `python -m app.server`
không sinh hai bản SocketIO khác nhau (module __main__ và module app.server)."""
from engineio.payload import Payload
from flask_socketio import SocketIO

# Bài học View desktop (hệ cũ 10.24): long-polling gộp nhiều packet; trần mặc định 16 làm vứt cả gói
Payload.max_decode_packets = 500

socketio = SocketIO()
