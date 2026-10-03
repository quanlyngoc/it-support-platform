// Tổng quan (đặc tả §11, Sổ tay 4.6): tổng máy, online, tỉ lệ online, phiếu sự cố + cảnh báo phần cứng đang mở, đồng hồ,
// biểu đồ, thẻ theo phòng; Phòng chờ / khu vực lạ tách riêng và KHÔNG cộng vào tổng (luật §8.2 hệ cũ).
// Mọi con số là số TUYỆT ĐỐI lấy từ Core — chỉ ghi đè (realtime `room_stats` hoặc tải lại), cấm cộng/trừ (bài học 10.10).
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { getJson } from "../api-client";
import type { Incident, IncidentSummary, ListResult, Room } from "../api-client/types";
import { useRealtime } from "../realtime-client";
import { OnlineChart } from "./OnlineChart";

export function DashboardPage() {
  const connected = useRealtime((s) => s.connected);
  const slow = connected ? 30000 : 5000; // có realtime: chỉ đối soát chậm; mất realtime: hỏi nhanh
  const q = useQuery({
    queryKey: ["rooms"],
    queryFn: () => getJson<ListResult<Room>>("/api/rooms"),
    refetchInterval: slow,
  });
  const sum = useQuery({
    queryKey: ["incidents", "summary"],
    queryFn: () => getJson<IncidentSummary>("/api/incidents/summary"),
    refetchInterval: slow,
  });
  if (q.isPending) return <p className="muted">Đang tải…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;

  const rooms = q.data.items;
  const official = rooms.filter((r) => r.official);
  const others = rooms.filter((r) => !r.official);
  const total = official.reduce((s, r) => s + r.total, 0);
  const online = official.reduce((s, r) => s + r.online, 0);
  const ratio = total ? Math.round((online / total) * 100) : 0;
  const n = (v: number | undefined) => (v === undefined ? "…" : v);

  return (
    <section>
      <div className="dash-head">
        <h1>Tổng quan</h1>
        <Clock />
      </div>
      <div className="tiles">
        <div className="tile"><b>{total}</b><span>Máy (phòng chính thức)</span></div>
        <div className="tile ok"><b>{online}</b><span>Đang online</span></div>
        <div className="tile"><b>{total - online}</b><span>Offline</span></div>
        <div className="tile"><b>{ratio}%</b><span>Tỉ lệ online</span></div>
        <div className={`tile${sum.data?.open ? " warn" : ""}`}>
          <b>{n(sum.data?.open)}</b><span>Phiếu sự cố đang mở</span>
        </div>
        <div className={`tile${sum.data?.hardware_open ? " warn" : ""}`}>
          <b>{n(sum.data?.hardware_open)}</b><span>Cảnh báo phần cứng</span>
        </div>
      </div>
      {official.length > 0 && (
        <>
          <h2>Online theo phòng</h2>
          <OnlineChart rooms={official} />
        </>
      )}
      <h2>Phòng máy</h2>
      <RoomGrid rooms={official} />
      {others.length > 0 && (
        <>
          <h2>Phòng chờ và khu vực khác <small className="muted">(không tính vào tổng)</small></h2>
          <RoomGrid rooms={others} />
        </>
      )}
      {rooms.length === 0 && <p className="muted">Chưa có máy nào báo về Core.</p>}
      <OpenIncidents interval={slow} />
    </section>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="clock">
      {now.toLocaleDateString("vi-VN", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" })}
      {" · "}
      <b>{now.toLocaleTimeString("vi-VN", { hour12: false })}</b>
    </span>
  );
}

function RoomGrid({ rooms }: { rooms: Room[] }) {
  return (
    <div className="rooms">
      {rooms.map((r) => (
        <Link key={r.id} to={`/rooms/${r.id}`} className="room">
          <span className="room-name">{r.name}</span>
          <span className="room-count"><b>{r.online}</b> / {r.total} online</span>
          <span className="bar"><i style={{ width: `${r.total ? (r.online / r.total) * 100 : 0}%` }} /></span>
        </Link>
      ))}
    </div>
  );
}

const TRANG_THAI: Record<Incident["status"], string> = { PENDING: "Chờ xử lý", PROCESSING: "Đang xử lý", DONE: "Xong" };

function OpenIncidents({ interval }: { interval: number }) {
  const q = useQuery({
    queryKey: ["incidents", "open"],
    queryFn: () => getJson<ListResult<Incident>>("/api/incidents?status=OPEN&limit=8"),
    refetchInterval: interval,
  });
  if (q.isPending || q.isError || q.data.items.length === 0) return null;
  return (
    <>
      <h2>Sự cố đang mở <small className="muted">(mới nhất)</small></h2>
      <table className="grid">
        <thead>
          <tr><th>Thời điểm</th><th>Máy</th><th>Phòng</th><th>Sự cố</th><th>Trạng thái</th></tr>
        </thead>
        <tbody>
          {q.data.items.map((i) => (
            <tr key={i.id}>
              <td>{i.created_at ? new Date(i.created_at).toLocaleString("vi-VN", { hour12: false }) : ""}</td>
              <td><b>{i.hostname}</b></td>
              <td>{i.room_name}</td>
              <td title={i.description}>{i.title}</td>
              <td>{TRANG_THAI[i.status] ?? i.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
