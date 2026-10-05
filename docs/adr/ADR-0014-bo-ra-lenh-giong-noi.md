# ADR-0014: Bỏ "ra lệnh bằng giọng nói" (Sổ tay 6.5) và cấu hình Gemini

- Ngày: 05/10/2026
- Trạng thái: Đã duyệt (chỉ đạo của người phụ trách dự án: "bỏ ghi âm và voice AI")

## Bối cảnh
Sổ tay 6.5 mang sang tính năng "AI Voice Command" của hệ cũ: trình duyệt ghi âm → `POST /api/voice_ai` → Gemini
phiên âm + phân tích → trả lệnh cho người dùng xác nhận. Người phụ trách không muốn giữ tính năng này. Câu hỏi đặt ra:
có phải làm 6.5 cho "chuyển đổi chuẩn" rồi mới bỏ không.

Đối chiếu hệ cũ (chỉ đọc, 05/10/2026):
- `D:\NetworkInventory\app.py`: chỉ một route `/api/voice_ai` (proxy Gemini, không ghi CSDL) + setting
  `gemini_api_key` (Cấu hình → Tích hợp).
- Agent `client.py`: không có action/route nào liên quan → bỏ không chạm hợp đồng agent v2 (`HOP_DONG.md`).
- Hệ thi (`D:\ExaminationSystem`): không gọi voice AI. `ffmpeg` mà hệ thi và hub cũ dùng là để VẼ SÓNG ÂM bài thi HSK,
  không phải ghi âm → không thuộc phạm vi bỏ.

## Quyết định
- KHÔNG làm 6.5; không có `POST /api/voice`, không ghi âm trên Desktop.
- Sổ tay 8.3 (Quản trị nền tảng) bỏ mục cấu hình Gemini; khi chuyển dữ liệu (9.1) không mang `gemini_api_key` sang.
- Bảng đối chiếu chức năng (cổng ra GĐ8, "100% Đạt"): dòng "AI Voice Command" ghi **"Bỏ theo quyết định — ADR-0014"**,
  tính là đã xử lý, không phải "chưa đạt".

## Phương án đã loại
Làm 6.5 rồi gỡ sau: tốn công, thêm khoá bí mật (Gemini) phải quản lý, trong khi tính năng không có dữ liệu hay
ràng buộc nào cần chuyển — bỏ ngay từ đầu không làm chuyển đổi kém chuẩn đi.

## Hệ quả
- Dự án đi thẳng từ 6.4 sang GĐ7 (7.1 StorageService).
- Thư mục dự kiến `app/integrations/gemini` (CLAUDE.md §2) không dùng tới.
- Muốn có lại về sau: một ADR mới; luồng cũ đã ghi ở trên (proxy ở Core, khoá chỉ ở Core, người dùng xác nhận trước).
