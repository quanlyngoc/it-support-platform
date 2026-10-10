// Chat theo phòng (Sổ tay 8.1) — gọi Core `/api/chat/*`, hệ LAB (hệ quản lý phòng máy; chat HSK do ThiHSK tự giữ).
import { create } from "zustand";
import { authFetch, getJson, jsonOf } from "../api-client";

export const SCOPE = "LAB";

export type Conv = { room_id: string; room_name: string; official: boolean; unread: number; last: string;
  last_admin: boolean; last_at: string | null };
export type Msg = { id: string; sender: string; is_admin: boolean; message: string; image: boolean; created_at: string | null };
export type Reacts = Record<string, { counts: Record<string, number>; mine: string }>;
export type Thread = { room: { id: string; name: string }; messages: Msg[]; reactions: Reacts; clear_token: string };
export type Me = { side: "admin" | "room"; name: string; rooms: { id: string; name: string }[] };
export type ChatEvent = { kind: "message" | "react" | "clear"; scope: string; room_id: string; room_name?: string;
  from_admin?: boolean; sender?: string; sender_id?: string; preview?: string };

const post = async <T>(path: string, body: unknown): Promise<T> => jsonOf<T>(await authFetch(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope: SCOPE, ...body as object }) }));

export const me = () => getJson<Me>(`/api/chat/me?scope=${SCOPE}`);
export const conversations = () => getJson<{ items: Conv[] }>(`/api/chat/conversations?scope=${SCOPE}`);
export const unread = () => getJson<{ unread: number }>(`/api/chat/unread?scope=${SCOPE}`);
export const thread = (roomId: string, since: string | null, active: boolean) => getJson<Thread>(
  `/api/chat/messages?scope=${SCOPE}&room_id=${roomId}${since ? `&since=${since}` : ""}${active ? "&active=true" : ""}`);
export const send = (roomId: string, message: string, image: string | null) =>
  post<Msg>("/api/chat/send", { room_id: roomId, message, image });
export const react = (msgId: string, emoji: string) => post<{ mine: string }>("/api/chat/react", { msg_id: msgId, emoji });
export const clear = (roomId: string, keep: boolean) =>
  post<{ deleted: number }>("/api/chat/clear", { room_id: roomId, keep });

// Ảnh tin nhắn cần token → tải bằng fetch rồi giữ blob URL (thẻ <img> không gửi được Bearer)
const imgCache = new Map<string, Promise<string>>();
export function imageUrl(msgId: string): Promise<string> {
  let p = imgCache.get(msgId);
  if (!p) {
    p = authFetch(`/api/chat/image/${msgId}`).then(async (r) => {
      if (!r.ok) throw new Error(`Ảnh lỗi ${r.status}`);
      return URL.createObjectURL(await r.blob());
    });
    p.catch(() => imgCache.delete(msgId));
    imgCache.set(msgId, p);
  }
  return p;
}

/** Ảnh dán → JPEG ≤ 1600 px, chất lượng 0,85, nền trắng (như compressImage của chatbox.js hệ cũ). */
export function compressImage(file: Blob, max = 1600, q = 0.85): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k);
      c.height = Math.round(img.height * k);
      const g = c.getContext("2d");
      if (!g) return reject(new Error("Không xử lý được ảnh"));
      g.fillStyle = "#fff";
      g.fillRect(0, 0, c.width, c.height);
      g.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", q));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Ảnh không đọc được"));
    };
    img.src = url;
  });
}

// ====================================================================== trạng thái dùng chung (huy hiệu, panel)
type ChatState = { open: boolean; room: string | null; unread: number; toast: ChatEvent | null; version: number };
export const useChat = create<ChatState>(() => ({ open: false, room: null, unread: 0, toast: null, version: 0 }));

export function openChat(room: string | null = null): void {
  useChat.setState((s) => ({ open: true, room: room ?? s.room, toast: null }));
}

/** Tiếng "ting" 2 nốt bằng Web Audio (không cần tệp âm thanh). */
let ac: AudioContext | null = null;
export function ding(): void {
  try {
    ac ??= new AudioContext();
    const t = ac.currentTime;
    for (const [f, d] of [[880, 0], [1320, 0.12]] as const) {
      const o = ac.createOscillator();
      const v = ac.createGain();
      o.frequency.value = f;
      v.gain.setValueAtTime(0.0001, t + d);
      v.gain.exponentialRampToValueAtTime(0.18, t + d + 0.02);
      v.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.25);
      o.connect(v).connect(ac.destination);
      o.start(t + d);
      o.stop(t + d + 0.3);
    }
  } catch {
    // không có âm thanh — vẫn còn toast + thông báo hệ điều hành
  }
}
