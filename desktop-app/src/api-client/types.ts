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
  model?: string;
  serial?: string;
  cpu?: string;
  ram?: string;
  disk?: string;
  client_version?: string;
  cmos_battery?: string;
  last_heartbeat_at?: string;
  is_online: boolean;
  channel: "socket" | "http" | "none";
  // chỉ có khi máy ONLINE (bài học 10.11 hệ cũ: máy offline không kèm số đo)
  cpu_usage?: number;
  ram_usage?: number;
  disk_usage?: string;
};

export type RoomDetail = Room & { devices: Device[]; live_layout: Record<string, { fx: number; fy: number }> };

export type ListResult<T> = { items: T[]; total: number };
