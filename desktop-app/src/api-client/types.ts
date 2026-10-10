// Kiểu dữ liệu TRẢ VỀ của Core. Kiểu GỬI LÊN sinh tự động trong schema.d.ts (`pnpm gen:api`); khi Core khai báo
// schema đầu ra (@output) thì các kiểu dưới đây cũng chuyển sang sinh tự động.

export type SessionInfo = {
  tenant_code: string;
  user_id: string;
  username: string;
  is_super: boolean;
  permissions: string[];
  room_ids: string[];
};

export type LoginResponse = {
  token: string;
  expires_at: string;
  user: { username: string; display_name?: string };
  session: SessionInfo;
};

export type ApiError = { message?: string; code?: string; detail?: unknown };

export type Room = {
  id: string;
  name: string;
  official: boolean;
  total: number;
  online: number;
};

export type Device = {
  id: string;
  hostname: string;
  room_id: string | null;
  room_name?: string;
  room_override?: string;
  move_seat?: string;
  mac?: string;
  ip?: string;
  seen_ip?: string; // IP máy chủ thấy (sau NAT/proxy) — có thể khác IP agent tự báo
  model?: string;
  serial?: string;
  cpu?: string;
  ram?: string;
  disk?: string;
  client_version?: string;
  mainboard?: string;
  network?: string;
  cmos_battery?: string;
  cpu_temp?: string;
  cpu_fan?: string;
  source?: string;
  last_heartbeat_at?: string;
  offline_at?: string;
  created_at?: string;
  is_online: boolean;
  channel: "socket" | "http" | "none";
  // chỉ có khi máy ONLINE (bài học 10.11 hệ cũ: máy offline không kèm số đo)
  cpu_usage?: number;
  ram_usage?: number;
  disk_usage?: string;
};

export type RoomDetail = Room & { devices: Device[]; live_layout: Record<string, { fx: number; fy: number }> };

export type ListResult<T> = { items: T[]; total: number };

export type IncidentItem = {
  n: number; text: string; at: string | null; by: string; done: boolean; done_at: string | null; done_by: string;
};
export type ItNote = { lines: number[]; text: string; at: string | null; by: string };

export type Incident = {
  id: string;
  hostname?: string;
  device_id?: string;
  room_name?: string;
  title?: string;
  description?: string;
  category?: string; // user | hardware_ram | hardware_disk | cmos
  status: "PENDING" | "PROCESSING" | "DONE";
  source?: "USER" | "SYSTEM_WATCHDOG" | string;
  reporter_name?: string;
  resolver_name?: string;
  created_at?: string;
  updated_at?: string;
  resolved_at?: string;
  items?: IncidentItem[]; // chỉ phiếu USER (người báo hỏng)
  it_notes?: ItNote[];
  rev?: number;
};

export type IncidentSummary = { open: number; pending: number; processing: number; hardware_open: number };

export type Health = { ok: boolean; service: string; version: string };

export type MoveResult = { moved: string[]; skipped: string[]; room_id: string; room_name: string };

export type MachineEvent = {
  event: string; // trao_phan_cung | doi_serial | doi_mac
  hostname?: string;
  other_host?: string;
  matched_by?: string;
  old_value?: string;
  new_value?: string;
  note?: string;
  created_at?: string;
};
