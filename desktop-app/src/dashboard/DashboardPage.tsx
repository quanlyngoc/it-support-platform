// Tổng quan (đặc tả §11): tổng máy, online, tỉ lệ online, thẻ theo phòng; Phòng chờ / khu vực lạ tách riêng và KHÔNG
// cộng vào tổng (luật §8.2 hệ cũ). Số online là số TUYỆT ĐỐI lấy từ Core — chỉ ghi đè, cấm cộng/trừ (bài học 10.10).
// Tạm làm mới 5 s/lần; khi kênh realtime (/desktop) xong thì ghi đè theo sự kiện batch_device_update.
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { getJson } from "../api-client";
import type { ListResult, Room } from "../api-client/types";

export function DashboardPage() {
  const q = useQuery({
    queryKey: ["rooms"],
    queryFn: () => getJson<ListResult<Room>>("/api/rooms"),
    refetchInterval: 5000,
  });
  if (q.isPending) return <p className="muted">Đang tải…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;

  const rooms = q.data.items;
  const official = rooms.filter((r) => r.official);
  const others = rooms.filter((r) => !r.official);
  const total = official.reduce((s, r) => s + r.total, 0);
  const online = official.reduce((s, r) => s + r.online, 0);
  const ratio = total ? Math.round((online / total) * 100) : 0;

  return (
    <section>
      <div className="tiles">
        <div className="tile"><b>{total}</b><span>Máy (phòng chính thức)</span></div>
        <div className="tile ok"><b>{online}</b><span>Đang online</span></div>
        <div className="tile"><b>{total - online}</b><span>Offline</span></div>
        <div className="tile"><b>{ratio}%</b><span>Tỉ lệ online</span></div>
      </div>
      <h2>Phòng máy</h2>
      <RoomGrid rooms={official} />
      {others.length > 0 && (
        <>
          <h2>Phòng chờ và khu vực khác <small className="muted">(không tính vào tổng)</small></h2>
          <RoomGrid rooms={others} />
        </>
      )}
      {rooms.length === 0 && <p className="muted">Chưa có máy nào báo về Core.</p>}
    </section>
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
