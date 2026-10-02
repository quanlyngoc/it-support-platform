# ADR-0003: Desktop: Tauri 2 + React + Vite + TypeScript

- Ngày: 02/10/2026
- Trạng thái: Đã duyệt

## Bối cảnh
Đặc tả V2 chỉ định Next.js; trong vỏ desktop Next.js phải ép xuất tĩnh, mất SSR/API routes/Server Actions.

## Quyết định
Tauri 2 + React 19 + Vite 8 + TypeScript, tạo từ mẫu React + TS chính thức của Tauri (quyết định của chủ đầu tư 02/10/2026).

## Phương án đã loại
Next.js xuất tĩnh; Electron (bộ cài 80–200 MB, RAM 150–300 MB).

## Hệ quả
Đội học TS/React và một ít Rust cho vỏ Tauri.
