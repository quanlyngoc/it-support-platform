// Giao bài / thu bài (Sổ tay 7.3) — gọi Core `/api/work/*`. Tệp đi theo LUỒNG (không nạp cả tệp vào RAM).
import { authFetch, jsonOf } from "../api-client";
import { useSession } from "../session/store";

export type Mode = "students" | "teachers" | "all";
export type Target = { room_ids: string[]; device_ids: string[]; mode: Mode };
export type Skipped = { hostname?: string; id?: string; reason: string };

export type SendFile = { name: string; ok: boolean; error?: string; note?: string };
export type SendRow = { hostname: string; room_name: string; status: "running" | "timeout" | "ok" | "partial" | "fail";
  saved?: number; skipped?: number; failed?: number; reason?: string; files?: SendFile[] };
export type SendStatus = { session_id: string; total: number; finished: number; complete: boolean; elapsed_s: number;
  deadline_s: number; dest_dir: string; files: string[]; overwrite: boolean; results: SendRow[] };

export type CollectRow = { hostname: string; room_name: string;
  status: "running" | "ok" | "nofile" | "nofolder" | "fail" | "offline"; files: string[]; count: number;
  deleted: boolean; error: string; size?: number | null; has_zip: boolean; saved_dir: string; saved_error: string };
export type CollectStatus = { session_id: string; total: number; submitted: number; complete: boolean; elapsed_s: number;
  deadline_s: number; ca: string; src: string; patterns: string[]; delete_after: boolean; save_thu: boolean;
  results: CollectRow[] };

export type Pushed = { hostname: string; room_name: string; folder: string; filename: string;
  status: "pushed" | "pending" | "deleted"; pushed_at: string | null; online: boolean };

const post = async <T>(path: string, body: unknown): Promise<T> => jsonOf<T>(await authFetch(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
const get = async <T>(path: string): Promise<T> => jsonOf<T>(await authFetch(path));

/** Tải 1 tệp vào lô (XHR để có % tải lên — fetch không báo tiến độ gửi). `name` giữ đường dẫn con khi chọn thư mục. */
export function uploadOne(f: File, name: string, batch: string,
                          onProgress: (sent: number) => void): Promise<{ batch_id: string; name: string; size: number }> {
  const { baseUrl, token } = useSession.getState();
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", `${baseUrl}/api/work/upload?name=${encodeURIComponent(name)}` +
      (batch ? `&batch=${encodeURIComponent(batch)}` : ""));
    x.setRequestHeader("Authorization", `Bearer ${token ?? ""}`);
    x.setRequestHeader("Content-Type", "application/octet-stream");
    x.upload.onprogress = (e) => onProgress(e.loaded);
    x.onload = () => {
      let body: { message?: string } & Record<string, unknown> = {};
      try {
        body = JSON.parse(x.responseText || "{}");
      } catch {
        // phản hồi không phải JSON
      }
      if (x.status === 401) useSession.getState().logout();
      if (x.status >= 200 && x.status < 300) resolve(body as unknown as { batch_id: string; name: string; size: number });
      else reject(new Error(body.message || `Lỗi ${x.status}`));
    };
    x.onerror = () => reject(new Error("Không kết nối được máy chủ"));
    x.send(f);
  });
}

export const startSend = (b: Target & { batch_id: string; dest_folder: string; overwrite: boolean }) =>
  post<{ session_id: string; total: number; skipped: Skipped[]; files: string[]; dest_dir: string; deadline_s: number }>(
    "/api/work/send", b);
export const sendStatus = (sid: string) => get<SendStatus>(`/api/work/send/${sid}`);
export const pushedList = () => get<{ items: Pushed[] }>("/api/work/pushed");
export const deletePushed = (room_ids: string[]) =>
  post<{ deleted: number; kept: number; machines: number; message: string }>("/api/work/pushed/delete", { room_ids });
export const startCollect = (b: Target & { src_folder: string; patterns: string[]; delete_after: boolean;
  save_thu: boolean; ca: string }) =>
  post<{ session_id: string; expected: number; total: number; skipped: Skipped[]; ca: string }>("/api/work/collect", b);
export const collectStatus = (sid: string) => get<CollectStatus>(`/api/work/collect/${sid}`);
export const zipAllPath = (sid: string) => `/api/work/collect/${sid}/zip`;
export const zipOnePath = (sid: string, host: string) => `/api/work/collect/${sid}/hosts/${encodeURIComponent(host)}/zip`;

// ====================================================================== lưu bài thu vào <thư mục>/<phòng>/<máy>/…
type Writable = { write(d: unknown): Promise<void>; close(): Promise<void>; abort?(): Promise<void> };
export type DirHandle = {
  name: string;
  getDirectoryHandle(n: string, o: { create: boolean }): Promise<DirHandle>;
  getFileHandle(n: string, o: { create: boolean }): Promise<{ createWritable(): Promise<Writable> }>;
};

export async function pickDir(): Promise<DirHandle | null> {
  const w = window as unknown as { showDirectoryPicker?: (o?: { mode: string }) => Promise<DirHandle> };
  if (!w.showDirectoryPicker) throw new Error("Máy này không hỗ trợ chọn thư mục — dùng \"Tải tất cả (.zip)\"");
  try {
    return await w.showDirectoryPicker({ mode: "readwrite" });
  } catch (e) {
    if ((e as Error).name === "AbortError") return null;
    throw e;
  }
}

async function writeTo(dir: DirHandle, name: string, res: Response): Promise<void> {
  const w = await (await dir.getFileHandle(name, { create: true })).createWritable();
  try {
    const rd = res.body?.getReader();
    if (!rd) throw new Error("Không đọc được dữ liệu");
    for (;;) {
      const { done, value } = await rd.read();
      if (done) break;
      await w.write(value);
    }
    await w.close();
  } catch (e) {
    await w.abort?.().catch(() => undefined);
    throw e;
  }
}

/** Giải nén bài của 1 máy vào <dir>/<phòng>/<máy>/… — từng tệp tải theo luồng từ Core (không giải nén trong RAM). */
export async function saveHost(dir: DirHandle, sid: string, row: CollectRow): Promise<number> {
  const base = `/api/work/collect/${sid}/hosts/${encodeURIComponent(row.hostname)}`;
  const { items } = await get<{ items: { path: string; size: number }[] }>(`${base}/entries`);
  const roomDir = await dir.getDirectoryHandle(row.room_name || "Khac", { create: true });
  const hostDir = await roomDir.getDirectoryHandle(row.hostname, { create: true });
  for (const it of items) {
    const segs = it.path.split("/").filter(Boolean);
    let d = hostDir;
    for (const s of segs.slice(0, -1)) d = await d.getDirectoryHandle(s, { create: true });
    const res = await authFetch(`${base}/entry?path=${encodeURIComponent(it.path)}`);
    if (!res.ok) throw new Error(`Tải "${it.path}" lỗi ${res.status}`);
    await writeTo(d, segs[segs.length - 1], res);
  }
  return items.length;
}
