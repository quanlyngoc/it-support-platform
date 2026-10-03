// Đang chạy trong vỏ Tauri hay trình duyệt thường (pnpm dev)? Plugin Tauri (updater, process…) chỉ gọi khi IN_TAURI.
import { getVersion } from "@tauri-apps/api/app";
import { isTauri } from "@tauri-apps/api/core";

export const IN_TAURI = isTauri();

/** Phiên bản ứng dụng đang chạy (thay cho FB_VER / CHATBOX_VER của web cũ — đặc tả §6: Trợ giúp → Giới thiệu). */
export async function appVersion(): Promise<string> {
  return IN_TAURI ? getVersion() : "dev (chạy trong trình duyệt)";
}
