// Lưu phiên đăng nhập: trong ứng dụng Tauri dùng plugin store (tệp riêng của ứng dụng — Sổ tay 4.5: KHÔNG localStorage);
// chạy thử bằng trình duyệt thường (pnpm dev) thì rơi về sessionStorage (mất khi đóng tab — chỉ để phát triển).
import { isTauri } from "@tauri-apps/api/core";
import { load, type Store } from "@tauri-apps/plugin-store";

const FILE = "session.json";
let store: Store | null = null;

async function tauriStore(): Promise<Store> {
  if (!store) store = await load(FILE, { autoSave: true, defaults: {} });
  return store;
}

export async function readValue<T>(key: string): Promise<T | undefined> {
  try {
    if (isTauri()) return (await (await tauriStore()).get<T>(key)) ?? undefined;
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : undefined;
  } catch {
    return undefined;
  }
}

export async function writeValue(key: string, value: unknown): Promise<void> {
  try {
    if (isTauri()) {
      const s = await tauriStore();
      if (value === undefined) await s.delete(key);
      else await s.set(key, value);
      return;
    }
    if (value === undefined) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // không lưu được thì phiên chỉ sống trong RAM — vẫn dùng được, chỉ phải đăng nhập lại khi mở lại ứng dụng
  }
}
