// Mở cửa sổ xem / điều khiển màn hình một máy (Sổ tay 5.4). Core cấp token + bảo agent mở tunnel tới relay; Desktop mở
// trang noVNC (URL Core trả, đã chứa token + mật khẩu VNC + view_only=0) trong CỬA SỔ CON. Đóng cửa sổ → báo Core để
// agent dừng tunnel (không tự nối lại nữa).
// Mỗi máy chỉ MỘT cửa sổ: bấm lại khi đang mở thì đưa cửa sổ đó lên trước, KHÔNG mở phiên mới (phiên mới làm agent dựng
// tunnel token khác → cửa sổ cũ rớt).
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { authFetch, jsonOf } from "../api-client";
import { useSession } from "../session/store";
import { IN_TAURI } from "../shared/platform";

type OpenRes = { hostname: string; token: string; channel: string; viewer_url: string };
const browserWins = new Map<string, Window>();

const label = (host: string) => `vnc-${host.replace(/[^A-Za-z0-9_-]/g, "_")}`;

async function close(deviceId: string, token: string) {
  try {
    await authFetch(`/api/devices/${encodeURIComponent(deviceId)}/vnc/close`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
    });
  } catch {
    // mất kết nối Core: agent tự dừng khi relay đóng phiên (viewer không còn)
  }
}

/** Mở (hoặc đưa lên trước) cửa sổ điều khiển; ném Error với thông báo tiếng Việt khi Core từ chối. */
export async function openVnc(dev: { id: string; hostname: string }): Promise<void> {
  const lb = label(dev.hostname);
  if (IN_TAURI) {
    const cur = await WebviewWindow.getByLabel(lb);
    if (cur) {
      await cur.setFocus();
      return;
    }
  } else {
    const w = browserWins.get(lb);
    if (w && !w.closed) {
      w.focus();
      return;
    }
  }
  const r = await jsonOf<OpenRes>(await authFetch(`/api/devices/${encodeURIComponent(dev.id)}/vnc/open`,
    { method: "POST" }));
  const url = /^https?:\/\//i.test(r.viewer_url) ? r.viewer_url : useSession.getState().baseUrl + r.viewer_url;
  if (IN_TAURI) {
    const w = new WebviewWindow(lb, {
      url, title: `Điều khiển ${r.hostname}`, width: 1366, height: 820, minWidth: 800, minHeight: 500, center: true,
    });
    void w.once("tauri://error", () => void close(dev.id, r.token));
    void w.once("tauri://destroyed", () => void close(dev.id, r.token));
    return;
  }
  const w = window.open(url, lb);
  if (!w) {
    void close(dev.id, r.token);
    throw new Error("Trình duyệt chặn cửa sổ bật lên — cho phép pop-up cho trang này rồi thử lại.");
  }
  browserWins.set(lb, w);
  const t = setInterval(() => {
    if (w.closed) {
      clearInterval(t);
      browserWins.delete(lb);
      void close(dev.id, r.token);
    }
  }, 1500);
}
