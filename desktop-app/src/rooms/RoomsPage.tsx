// Danh sách phòng (Sổ tay 5.2): tìm theo tên; phòng chính thức trước, Phòng chờ / khu vực khác tách riêng. Dùng chung
// cache ["rooms"] với Tổng quan nên số online cũng được ghi đè theo realtime (Layout).
import { lazy, Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { ListResult, Room } from "../api-client/types";
import { useRealtime } from "../realtime-client";
import { useCan } from "../shared/perm";
import { RoomGrid } from "./RoomGrid";

// Giao/thu bài NHIỀU phòng (Sổ tay 7.3 — như panel "Truyền tệp" trang chủ hệ cũ), chỉ nạp khi mở
const WorkDialog = lazy(() => import("../work/WorkDialog").then((m) => ({ default: m.WorkDialog })));

export function RoomsPage() {
  const connected = useRealtime((s) => s.connected);
  const [filter, setFilter] = useState("");
  const [work, setWork] = useState(false);
  const canControl = useCan("device.control");
  const q = useQuery({
    queryKey: ["rooms"],
    queryFn: () => getJson<ListResult<Room>>("/api/rooms"),
    refetchInterval: connected ? 30000 : 5000,
  });
  if (q.isPending) return <p className="muted">Đang tải…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;

  const f = filter.trim().toLowerCase();
  const rooms = q.data.items.filter((r) => !f || r.name.toLowerCase().includes(f));
  const official = rooms.filter((r) => r.official);
  const others = rooms.filter((r) => !r.official);
  return (
    <section>
      <div className="dash-head">
        <h1>Phòng máy <small className="muted">{q.data.items.filter((r) => r.official).length} phòng</small></h1>
        <div className="toolbar">
          {canControl && (
            <button className="ghost" onClick={() => setWork(true)} title="Giao bài / thu bài nhiều phòng cùng lúc">
              📤 Truyền tệp</button>
          )}
          <input className="search" value={filter} onChange={(e) => setFilter(e.target.value)}
                 placeholder="Tìm phòng (vd 301)" aria-label="Tìm phòng" />
        </div>
      </div>
      <RoomGrid rooms={official} />
      {others.length > 0 && (
        <>
          <h2>Phòng chờ và khu vực khác <small className="muted">(không tính vào tổng)</small></h2>
          <RoomGrid rooms={others} />
        </>
      )}
      {rooms.length === 0 && <p className="muted">{f ? "Không có phòng khớp." : "Chưa có máy nào báo về Core."}</p>}
      {work && (
        <Suspense fallback={<p className="muted">Đang mở giao/thu bài…</p>}>
          <WorkDialog preset={{ pickRooms: true }} onClose={() => setWork(false)} />
        </Suspense>
      )}
    </section>
  );
}
