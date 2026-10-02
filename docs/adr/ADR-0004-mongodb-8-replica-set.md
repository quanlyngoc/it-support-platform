# ADR-0004: MongoDB 8.0 replica set 3 node

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
Cần transaction, change streams, tự chuyển node khi hỏng; SQLite chặn hub gevent (bài học 10.16).

## Quyết định
MongoDB Community 8.0.x, replica set `rs0` 3 node, `w=majority`; DB `itm_core` và `itm_master` tách riêng; driver PyMongo đồng bộ.

## Phương án đã loại
Một node đơn; Motor (hết hỗ trợ 14/05/2026); MongoDB 9.0 (Community chưa GA).

## Hệ quả
3 VM; sao lưu đêm và khôi phục thử hằng tháng.

## Bổ sung 02/10/2026
Giai đoạn dựng thử dùng MongoDB Atlas thay 3 VM — xem ADR-0013. Cụm 3 VM tại trường vẫn là đích cho giai đoạn chạy thật.
