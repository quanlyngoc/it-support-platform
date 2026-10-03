// Kênh realtime tới Core — namespace /desktop, chỉ websocket, xác thực bằng token (Sổ tay 4.5).
// Mất kết nối → dải đỏ "MẤT KẾT NỐI"; nối lại → tải lại SỐ TUYỆT ĐỐI (không tin số đang hiển thị — bài học 10.10).
import { io, type Socket } from "socket.io-client";
import { create } from "zustand";

export type DeviceUpdate = {
  hostname: string;
  device_id: string | null;
  room_name: string;
  is_online: boolean;
  state_changed: boolean;
  cpu_usage?: number;
  ram_usage?: number;
  disk_usage?: string;
  client_version?: string;
};

export type BatchDeviceUpdate = {
  room_id?: string;
  devices: DeviceUpdate[];
  room_stats: Record<string, number>;
  total_online: number;
};

type RealtimeState = { connected: boolean; everConnected: boolean };
export const useRealtime = create<RealtimeState>(() => ({ connected: false, everConnected: false }));

let socket: Socket | null = null;

export function connectRealtime(baseUrl: string, token: string, onResync: () => void): Socket {
  disconnectRealtime();
  const s = io(`${baseUrl}/desktop`, { transports: ["websocket"], auth: { token }, reconnectionDelayMax: 5000 });
  s.on("connect", () => {
    useRealtime.setState({ connected: true, everConnected: true });
    onResync(); // vừa nối (lại): đồng bộ lại số tuyệt đối + đăng ký lại các phòng đang xem
  });
  s.on("disconnect", () => useRealtime.setState({ connected: false }));
  s.on("connect_error", () => useRealtime.setState({ connected: false }));
  socket = s;
  return s;
}

export function disconnectRealtime(): void {
  socket?.removeAllListeners();
  socket?.disconnect();
  socket = null;
  useRealtime.setState({ connected: false });
}

export function realtime(): Socket | null {
  return socket;
}

/** Gửi sự kiện có ack `{ok, error?}` (Core luôn trả) — hết 8 s không trả lời coi như lỗi. */
export function request(event: string, data: unknown): Promise<{ ok: boolean; error?: string }> {
  const s = socket;
  if (!s || !s.connected) return Promise.resolve({ ok: false, error: "Mất kết nối máy chủ" });
  return s.timeout(8000).emitWithAck(event, data).catch(() => ({ ok: false, error: "Máy chủ không phản hồi" }));
}
