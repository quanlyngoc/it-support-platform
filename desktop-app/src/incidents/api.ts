// Gọi API sự cố + kênh cảnh báo + log máy trạm của Core (Sổ tay 8.2). Core kiểm quyền / phạm vi phòng ở MỌI API.
import { authFetch, jsonOf, saveBlob } from "../api-client";
import type { Incident } from "../api-client/types";

export const TRANG_THAI: Record<Incident["status"], string> = {
  PENDING: "Chờ xử lý", PROCESSING: "Đang xử lý", DONE: "Đã xong",
};

export type IncidentUpdate = {
  action: "new" | "append" | "note" | "resolve"; id: string; hostname: string; room_name: string;
  status: Incident["status"]; by: string; title: string;
};

async function post<T>(path: string, body: unknown): Promise<T> {
  return jsonOf<T>(await authFetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }));
}

export async function reportIssue(deviceId: string, description: string) {
  return post<{ incident: Incident; appended: boolean }>("/api/incidents", { device_id: deviceId, description });
}

export async function appendIssue(id: string, text: string) {
  return (await post<{ incident: Incident }>(`/api/incidents/${id}/append`, { text })).incident;
}

export async function noteIssue(id: string, text: string) {
  return (await post<{ incident: Incident }>(`/api/incidents/${id}/note`, { text })).incident;
}

export async function resolveIssue(id: string, text: string, lines: number[]) {
  return (await post<{ incident: Incident }>(`/api/incidents/${id}/resolve`, { text, lines })).incident;
}

export type IncidentFilter = {
  status?: string; source?: string; q?: string; date_from?: string; date_to?: string; room_id?: string;
};

export function filterQuery(f: IncidentFilter): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v) p.set(k, v);
  return p.toString();
}

/** Tải tệp Excel (GET kèm token) rồi lưu về máy. */
export async function download(path: string, filename: string): Promise<void> {
  const res = await authFetch(path);
  if (!res.ok) await jsonOf(res); // ném lỗi tiếng Việt của Core
  saveBlob(await res.blob(), filename);
}

export function stamp(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

export type ClientLog = { id: string; hostname: string; mac: string; ip: string; context: string; error: string;
  created_at: string | null };

export type AlertCfg = {
  smtp_server: string; smtp_port: string; sender_email: string; receiver_email: string; telegram_chat_id: string;
  has_gmail_app_password: boolean; has_telegram_bot_token: boolean; gmail_app_password_mask: string;
  telegram_bot_token_mask: string; telegram_ready: boolean; email_ready: boolean;
};

export type AlertSave = Partial<Pick<AlertCfg, "smtp_server" | "smtp_port" | "sender_email" | "receiver_email" |
  "telegram_chat_id">> & {
  gmail_app_password?: string; telegram_bot_token?: string;
  clear_gmail_app_password?: boolean; clear_telegram_bot_token?: boolean;
};

export async function saveAlerts(body: AlertSave): Promise<AlertCfg> {
  return jsonOf<AlertCfg>(await authFetch("/api/settings/alerts", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }));
}

export async function testAlerts(channel: "email" | "telegram", form: AlertSave) {
  return post<{ ok: boolean; message: string }>("/api/settings/alerts/test", { ...form, channel });
}
