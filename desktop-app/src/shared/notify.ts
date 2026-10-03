// Thông báo cấp hệ điều hành (Windows tự nháy nút taskbar) — bài học chat hệ cũ: huy hiệu trong trang không đủ khi người
// dùng đang ở cửa sổ khác. Chỉ báo khi cửa sổ KHÔNG được xem; xin quyền một lần; bị từ chối thì im lặng.
import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";

let allowed: Promise<boolean> | null = null;

function permission(): Promise<boolean> {
  allowed ??= (async () => {
    try {
      if (await isPermissionGranted()) return true;
      return (await requestPermission()) === "granted";
    } catch {
      return false;
    }
  })();
  return allowed;
}

/** Người dùng đang nhìn cửa sổ này (không thu nhỏ, không ở ứng dụng khác). */
export function pageActive(): boolean {
  return !document.hidden && document.hasFocus();
}

export async function notifyOs(title: string, body: string): Promise<void> {
  if (pageActive() || !(await permission())) return;
  try {
    sendNotification({ title, body });
  } catch {
    // nền tảng không hỗ trợ — trong ứng dụng vẫn thấy qua Dashboard
  }
}
