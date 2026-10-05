// Kênh của trình quản lý tệp (Sổ tay 7.2) — một đường code cho mọi nguồn, như FbPane.send của fbrowser.js hệ cũ:
//  - máy trạm: socket /desktop `fs_request` → agent → `fs_response` (Core gắn reply_sid, trả về ĐÚNG Desktop này);
//    tiến độ `fs_progress` mỗi 512 KB;
//  - "Máy chủ" (kho riêng của tổ chức): HTTP POST /api/files/srv — CÙNG tên lệnh, cùng dạng kết quả {ok, error, …}.
// BYTES không bao giờ đi qua socket: tải lên / tải về bằng HTTP theo token (Core cấp), theo luồng.
import type { Socket } from "socket.io-client";
import { authFetch, jsonOf, saveBlob } from "../api-client";
import { realtime, request } from "../realtime-client";

export const SRV = "__SRV__";
export const LONG = 30 * 60 * 1000; // truyền tệp lớn: tối đa 30 phút (như hệ cũ)

export type FsItem = { name: string; type: "dir" | "file"; size: number; mtime: number };
export type FsRes = {
  ok: boolean; error?: string; op?: string; path?: string; items?: FsItem[]; name?: string; zipped?: boolean;
  token?: string; filename?: string;
};
export type Progress = { sent: number; total: number; name?: string };

const pending = new Map<string, (r: FsRes) => void>();
const progress = new Map<string, (p: Progress) => void>();
const wired = new WeakSet<Socket>();
let seq = 0;

/** Gắn bộ nghe fs_response / fs_progress MỘT lần cho mỗi socket (đăng nhập lại → socket mới → gắn lại). */
function wire(): Socket | null {
  const s = realtime();
  if (s && !wired.has(s)) {
    wired.add(s);
    s.on("fs_response", (r: FsRes & { req_id?: string }) => {
      const id = r.req_id ?? "";
      const cb = pending.get(id);
      if (cb) {
        pending.delete(id);
        progress.delete(id);
        cb(r);
      }
    });
    s.on("fs_progress", (p: Progress & { req_id?: string }) => progress.get(p.req_id ?? "")?.(p));
  }
  return s;
}

export async function fsSend(src: string, op: string, extra: Record<string, unknown> = {},
                             opts: { ms?: number; onProgress?: (p: Progress) => void } = {}): Promise<FsRes> {
  if (src === SRV) {
    try {
      const res = await authFetch("/api/files/srv", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op, ...extra }),
      });
      return await jsonOf<FsRes>(res);
    } catch (e) {
      return { ok: false, error: (e as Error).message };
    }
  }
  if (!wire()) return { ok: false, error: "Mất kết nối máy chủ" };
  const id = `fb_${Date.now()}_${++seq}`;
  return new Promise<FsRes>((resolve) => {
    const done = (r: FsRes) => {
      window.clearTimeout(timer);
      pending.delete(id);
      progress.delete(id);
      resolve(r);
    };
    const timer = window.setTimeout(() => {
      if (pending.has(id)) done({ ok: false, error: "⏱ Máy không phản hồi (đang tắt hoặc mất kết nối?)" });
    }, opts.ms ?? 15000);
    pending.set(id, done);
    if (opts.onProgress) progress.set(id, opts.onProgress);
    void request("fs_request", { device_id: src, req_id: id, op, ...extra }).then((a) => {
      if (!a.ok && pending.has(id)) done({ ok: false, error: a.error ?? "Không gửi được lệnh" });
    });
  });
}

// ====================================================================== tệp ↔ Core (HTTP, theo token)
export async function newToken(): Promise<string> {
  return (await jsonOf<{ token: string }>(await authFetch("/api/files/token", { method: "POST" }))).token;
}

/** Đưa tệp của máy bạn lên Core → token để máy trạm tải (`push` với `/fs_serve/<token>`). */
export async function putFile(f: Blob, name: string): Promise<{ token: string; filename: string }> {
  return jsonOf(await authFetch(`/api/files/upload?name=${encodeURIComponent(name)}`, {
    method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" },
  }));
}

export async function srvUpload(dir: string, f: Blob, name: string): Promise<FsRes> {
  try {
    return await jsonOf<FsRes>(await authFetch(
      `/api/files/srv/upload?path=${encodeURIComponent(dir)}&name=${encodeURIComponent(name)}`,
      { method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" } }));
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

export const pulledPath = (tok: string) => `/api/files/pulled/${encodeURIComponent(tok)}`;
export const srvFilePath = (path: string) => `/api/files/srv/download?path=${encodeURIComponent(path)}`;

// ====================================================================== lưu về máy bạn (ghi THẲNG ra đĩa theo luồng)
// Hỏi chỗ lưu NGAY lúc bấm (trình duyệt chỉ cho mở hộp chọn tệp trong thao tác của người dùng) rồi mới bảo máy trạm nộp
// tệp lên; dữ liệu đi từ Core thẳng vào tệp đích (File System Access API của WebView2) — không giữ cả tệp trong RAM.
// Không có API đó (trình duyệt cũ) → dự phòng tải Blob.
type Writable = { write(d: unknown): Promise<void>; close(): Promise<void>; abort?(): Promise<void> };
type FileHandle = { createWritable(): Promise<Writable>; name: string };
type DirHandle = { getFileHandle(name: string, o: { create: boolean }): Promise<FileHandle> };
type Pickers = {
  showSaveFilePicker?: (o: { suggestedName: string }) => Promise<FileHandle>;
  showDirectoryPicker?: (o?: { mode: string }) => Promise<DirHandle>;
};

export type Sink = (name: string) => Promise<(res: Response) => Promise<void>>;

async function toWritable(h: FileHandle, res: Response): Promise<void> {
  const w = await h.createWritable();
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

/** Chọn nơi lưu cho `names` (1 tệp → hộp "Lưu thành"; nhiều tệp → chọn thư mục). null = người dùng bỏ. */
export async function pickSink(names: string[]): Promise<Sink | null> {
  const w = window as unknown as Pickers;
  try {
    if (names.length === 1 && w.showSaveFilePicker) {
      const h = await w.showSaveFilePicker({ suggestedName: names[0] });
      return async () => (res) => toWritable(h, res);
    }
    if (names.length > 1 && w.showDirectoryPicker) {
      const d = await w.showDirectoryPicker({ mode: "readwrite" });
      return async (name) => {
        const h = await d.getFileHandle(name, { create: true });
        return (res) => toWritable(h, res);
      };
    }
  } catch (e) {
    if ((e as Error).name === "AbortError") return null;
    throw e;
  }
  return async (name) => async (res) => saveBlob(await res.blob(), name);
}
