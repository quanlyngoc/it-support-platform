# ADR-0013: MongoDB Atlas cho giai đoạn dựng thử (sửa ADR-0004, bổ sung ADR-0002)

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt (chỉ đạo của người phụ trách dự án)

## Bối cảnh
Chưa có 3 VM MongoDB tại trường (GĐ1 cần người vận hành có quyền Administrator). Người phụ trách cung cấp sẵn một
cụm MongoDB Atlas để dựng Platform-Core ngay. Đồng thời có chỉ đạo: giai đoạn dựng thử bỏ qua yếu tố bảo mật,
siết lại khi hoàn thiện trên cơ sở hệ thống cũ.

Đo ngày 02/10/2026 (chỉ `ping`/`hello`): MongoDB 8.0.34, replica set `atlas-m146mq-shard-0` 3 node, RTT ≈ 55 ms
từ máy chủ hiện tại. Đăng nhập qua Core trên Atlas: ≈ 0,5 s; kiểm phiên lần đầu ≈ 190 ms, các lần sau ≈ 11 ms (đệm RAM).

## Quyết định
- Dùng Atlas cho Core (`itm_core`) và Master (`itm_master`) trong giai đoạn dựng thử. Vẫn là replica set 3 node,
  `w=majority`, PyMongo đồng bộ — **mã nguồn không đổi** khi chuyển sang cụm tại trường (chỉ đổi `MONGO_URI`).
- Chuỗi kết nối chỉ nằm trong `platform-core/.env` (đã `.gitignore`), không ghi vào tài liệu/mã.
- Vì RTT ~55 ms, thiết kế bắt buộc: đệm phiên 15 s (`auth.service._CACHE`), chụp quyền vào phiên lúc đăng nhập,
  trạng thái online của máy giữ trong RAM và ghi gộp (GĐ3) — không truy vấn CSDL trong vòng lặp nhịp tim.
- Test mặc định chạy trên mongomock; nhóm `-m atlas` chạy trên database tạm `itm_test_<ngẫu nhiên>` và xoá sau khi chạy.

## Phương án đã loại
Chờ dựng xong 3 VM rồi mới viết Core (chậm toàn bộ đường găng); chạy một node MongoDB cục bộ trên máy chủ hệ cũ
(đụng tài nguyên máy đang phục vụ 888 máy trạm).

## Hệ quả
- Các mục "Hoãn bảo mật" trong `docs/TIEN_DO.md` phải xong trước khi chạy thật: đổi mật khẩu `admin` của Atlas,
  user riêng theo DB, giới hạn Network Access theo IP, kiểm region theo Luật Bảo vệ dữ liệu cá nhân 2025.
- Quyết định on-prem của ADR-0002 cho giai đoạn **chạy thật** vẫn giữ nguyên; khi về cụm tại trường dùng
  `mongodump`/`mongorestore` từ Atlas hoặc khởi tạo lại bằng `python -m app.db.init` (dữ liệu dựng thử không bắt buộc giữ).
- Agent máy trạm đi qua Core, không bao giờ nối thẳng tới Atlas.
