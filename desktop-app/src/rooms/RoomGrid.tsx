// Thẻ phòng: tên, số online / tổng (số TUYỆT ĐỐI từ Core), thanh tỉ lệ. Dùng ở Tổng quan và trang Phòng máy.
import { Link } from "react-router";
import type { Room } from "../api-client/types";

export function RoomGrid({ rooms }: { rooms: Room[] }) {
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
