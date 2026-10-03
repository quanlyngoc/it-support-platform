// Tự cập nhật Desktop (Sổ tay 4.4 / 4.7): hỏi `desktop/latest.json` (endpoint trong tauri.conf.json); bộ cài phải có chữ
// ký minisign khớp pubkey trong cấu hình, và `requireSignedVersion` buộc số phiên bản nằm TRONG chữ ký (không ghép được
// số phiên bản này với bộ cài của bản khác). Lỗi mạng / chưa có endpoint → chỉ ghi lỗi, KHÔNG chặn người dùng làm việc.
import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { create } from "zustand";
import { IN_TAURI } from "./platform";

type UpdateState = {
  update: Update | null;
  checking: boolean;
  installing: boolean;
  progress: number | null; // 0–100; null = chưa biết dung lượng
  error: string | null;
  checkedAt: Date | null;
};

export const useUpdate = create<UpdateState>(() => ({
  update: null, checking: false, installing: false, progress: null, error: null, checkedAt: null,
}));

export async function checkUpdate(): Promise<void> {
  if (!IN_TAURI || useUpdate.getState().checking || useUpdate.getState().installing) return;
  useUpdate.setState({ checking: true, error: null });
  try {
    useUpdate.setState({ update: await check({ timeout: 15000 }) });
  } catch (e) {
    useUpdate.setState({ error: String(e) });
  } finally {
    useUpdate.setState({ checking: false, checkedAt: new Date() });
  }
}

export async function installUpdate(): Promise<void> {
  const u = useUpdate.getState().update;
  if (!u || useUpdate.getState().installing) return;
  useUpdate.setState({ installing: true, error: null, progress: null });
  let total = 0;
  let got = 0;
  try {
    await u.downloadAndInstall((ev) => {
      if (ev.event === "Started") total = ev.data.contentLength ?? 0;
      else if (ev.event === "Progress" && total) {
        got += ev.data.chunkLength;
        useUpdate.setState({ progress: Math.min(100, Math.round((got * 100) / total)) });
      }
    });
    await relaunch(); // Windows: bộ cài NSIS (passive) tự đóng ứng dụng rồi mở lại — dòng này cho nền tảng khác
  } catch (e) {
    useUpdate.setState({ installing: false, error: String(e) });
  }
}
