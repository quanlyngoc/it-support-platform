// Chi tiết phòng (Sổ tay 5.2 — bản đầu): danh sách máy + CPU/RAM theo thời gian thực. Đăng ký room realtime của phòng;
// mỗi batch_device_update GHI ĐÈ trạng thái từng máy + số online tuyệt đối. Mọi chỗ vẽ số đo bọc is_online — máy
// offline KHÔNG có cpu_usage/ram_usage (bài học 10.11 hệ cũ: lòi "undefined%").
import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { getJson } from "../api-client";
import type { Device, RoomDetail } from "../api-client/types";
import { realtime, request, useRealtime, type BatchDeviceUpdate } from "../realtime-client";

export function RoomPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const connected = useRealtime((s) => s.connected);
  const q = useQuery({
    queryKey: ["room", id],
    queryFn: () => getJson<RoomDetail>(`/api/rooms/${encodeURIComponent(id)}`),
    refetchInterval: connected ? 30000 : 5000, // có realtime thì chỉ đối soát chậm; mất realtime thì poll nhanh
  });

  useEffect(() => {
    const s = realtime();
    if (!s || !connected) return;
    void request("subscribe_room", { room_id: id });
    const onBatch = (p: BatchDeviceUpdate) => {
      if (p.room_id !== id) return;
      qc.setQueryData<RoomDetail>(["room", id], (old) => {
        if (!old) return old;
        const byId = new Map(p.devices.filter((d) => d.device_id).map((d) => [d.device_id as string, d]));
        const devices = old.devices.map((d): Device => {
          const u = byId.get(d.id);
          if (!u) return d;
          const { cpu_usage: _c, ram_usage: _r, disk_usage: _d, ...rest } = d; // offline → bỏ số đo cũ
          return u.is_online ? { ...rest, is_online: true, cpu_usage: u.cpu_usage, ram_usage: u.ram_usage,
                                 disk_usage: u.disk_usage } : { ...rest, is_online: false };
        });
        return { ...old, devices, online: p.room_stats[id] ?? old.online };
      });
    };
    s.on("batch_device_update", onBatch);
    return () => {
      s.off("batch_device_update", onBatch);
      void request("unsubscribe_room", { room_id: id });
    };
  }, [id, connected, qc]);

  if (q.isPending) return <p className="muted">Đang tải…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;
  const r = q.data;
  return (
    <section>
      <p><Link to="/">← Tổng quan</Link></p>
      <h1>{r.name} <small className="muted">{r.online} / {r.total} online</small></h1>
      <table className="grid">
        <thead>
          <tr><th>Máy</th><th>Trạng thái</th><th>CPU</th><th>RAM</th><th>IP</th><th>MAC</th><th>Model</th><th>Agent</th></tr>
        </thead>
        <tbody>
          {r.devices.map((d) => <Row key={d.id} d={d} />)}
        </tbody>
      </table>
    </section>
  );
}

function Row({ d }: { d: Device }) {
  return (
    <tr className={d.is_online ? "" : "off"}>
      <td>
        <b>{d.hostname}</b>
        {d.room_override && <span className="badge" title="Đã chuyển phòng tay (Move PC)">chuyển tay</span>}
      </td>
      <td>{d.is_online ? (d.channel === "http" ? "Online (mất kênh socket)" : "Online") : "Offline"}</td>
      <td>{d.is_online && d.cpu_usage !== undefined ? `${d.cpu_usage}%` : "—"}</td>
      <td>{d.is_online && d.ram_usage !== undefined ? `${d.ram_usage}%` : "—"}</td>
      <td>{d.ip ?? ""}</td>
      <td>{d.mac ?? ""}</td>
      <td>{d.model ?? ""}</td>
      <td>{d.client_version ?? ""}</td>
    </tr>
  );
}
