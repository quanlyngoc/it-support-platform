// Trang Báo cáo (Sổ tay 8.2) — thay /admin/stats (thống kê sử dụng năm + Excel), /reports + /report/<ngày> (theo ngày)
// và /history (lịch sử RAM / ổ cứng) của hệ cũ. Số liệu từ `usage_stats` (+1 phút / máy online / phút). Người bị giới
// hạn phòng chỉ thấy phòng của mình (Core lọc).
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { ListResult, Room } from "../api-client/types";
import { download } from "../incidents/api";
import { fmtTime } from "../shared/metrics";
import { useCan } from "../shared/perm";
import { HoursChart } from "./HoursChart";

type Machine = { device_id: string; hostname: string; room_name: string; minutes: number; days: number; deleted?: boolean };
type Usage = { year: number; month: number | null; total_minutes: number; machines: number; used: number;
  rooms: { room_name: string; minutes: number; used: number; machines: Machine[] }[] };
type Point = { period: string; minutes: number; machines: number };
type DayRow = { device_id: string; hostname: string; room_name: string; minutes: number; ram: string;
  ram_changed_at: string | null };
type HwRow = { id: string; created_at: string | null; hostname: string; room_name: string; mac: string; part: string;
  event_type: string; old_value: string; new_value: string; status: string };

type Tab = "usage" | "series" | "hw";
const gio = (m: number) => Math.round(m / 6) / 10;
const shortName = (n: string) => n.match(/\d{3}/)?.[0] ?? n;
const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export function ReportsPage() {
  const [tab, setTab] = useState<Tab>("usage");
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => getJson<ListResult<Room>>("/api/rooms") });
  const roomList = (rooms.data?.items ?? []).filter((r) => r.total > 0);
  return (
    <section>
      <div className="dash-head">
        <h1>Báo cáo</h1>
        <div className="seg">
          <button className={tab === "usage" ? "on" : ""} onClick={() => setTab("usage")}>Thống kê sử dụng</button>
          <button className={tab === "series" ? "on" : ""} onClick={() => setTab("series")}>Theo ngày / tháng</button>
          <button className={tab === "hw" ? "on" : ""} onClick={() => setTab("hw")}>Lịch sử RAM / ổ cứng</button>
        </div>
      </div>
      {tab === "usage" && <UsageTab rooms={roomList} />}
      {tab === "series" && <SeriesTab rooms={roomList} />}
      {tab === "hw" && <HardwareTab />}
    </section>
  );
}

function RoomSelect({ rooms, value, onChange }: { rooms: Room[]; value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Phòng">
      <option value="">Mọi phòng</option>
      {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
    </select>
  );
}

// ====================================================================== thống kê sử dụng (năm / tháng)
function UsageTab({ rooms }: { rooms: Room[] }) {
  const canExport = useCan("report.export");
  const now = new Date().getFullYear();
  const [year, setYear] = useState(now);
  const [month, setMonth] = useState(0);
  const [room, setRoom] = useState("");
  const [openRoom, setOpenRoom] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const p = new URLSearchParams({ year: String(year) });
  if (month) p.set("month", String(month));
  if (room) p.set("room_id", room);
  const qs = p.toString();
  const u = useQuery({ queryKey: ["reports", "usage", qs], queryFn: () => getJson<Usage>(`/api/reports/usage?${qs}`) });
  const chart = useMemo(() => {
    const rs = u.data?.rooms ?? [];
    return { labels: rs.map((r) => shortName(r.room_name)), hours: rs.map((r) => gio(r.minutes)) };
  }, [u.data]);

  return (
    <>
      <div className="toolbar filters">
        <select value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Năm">
          {Array.from({ length: 6 }, (_, i) => now - i).map((y) => <option key={y} value={y}>Năm {y}</option>)}
        </select>
        <select value={month} onChange={(e) => setMonth(Number(e.target.value))} aria-label="Tháng">
          <option value={0}>Cả năm</option>
          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>Tháng {m}</option>)}
        </select>
        <RoomSelect rooms={rooms} value={room} onChange={setRoom} />
        {canExport && (
          <button className="ghost" onClick={() => {
            setErr("");
            download(`/api/reports/usage/export?${qs}`,
                     `Thong_Ke_Su_Dung_${year}${month ? `_${pad(month)}` : ""}.xlsx`).catch((e: Error) => setErr(e.message));
          }}>Xuất Excel</button>
        )}
      </div>
      {err && <p className="error">{err}</p>}
      {u.isPending && <p className="muted">Đang tải…</p>}
      {u.isError && <p className="error">{u.error.message}</p>}
      {u.data && (
        <>
          <div className="tiles">
            <div className="tile"><b>{gio(u.data.total_minutes).toLocaleString("vi-VN")}</b><span>Tổng giờ sử dụng</span></div>
            <div className="tile ok"><b>{u.data.used}</b><span>Máy có dùng</span></div>
            <div className="tile"><b>{u.data.machines}</b><span>Tổng số máy</span></div>
            <div className="tile">
              <b>{u.data.used ? gio(u.data.total_minutes / u.data.used) : 0}</b><span>Giờ TB / máy có dùng</span>
            </div>
          </div>
          {u.data.rooms.length > 0 ? (
            <>
              <h2>Tổng giờ sử dụng theo phòng</h2>
              <HoursChart labels={chart.labels} hours={chart.hours} />
              <h2>Chi tiết theo phòng <small className="muted">(bấm để mở danh sách máy)</small></h2>
              {u.data.rooms.map((r) => (
                <div key={r.room_name} className="rp-room">
                  <button className="rp-head" onClick={() => setOpenRoom(openRoom === r.room_name ? null : r.room_name)}
                          aria-expanded={openRoom === r.room_name}>
                    <b>{r.room_name}</b>
                    <span className="muted">{r.used}/{r.machines.length} máy có dùng</span>
                    <span>{gio(r.minutes).toLocaleString("vi-VN")} giờ</span>
                    <span className="chev">{openRoom === r.room_name ? "▴" : "▾"}</span>
                  </button>
                  {openRoom === r.room_name && (
                    <table className="grid">
                      <thead><tr><th>STT</th><th>Tên máy</th><th className="num">Tổng phút</th>
                        <th className="num">Tổng giờ</th><th className="num">Số ngày có dùng</th></tr></thead>
                      <tbody>
                        {r.machines.map((m, i) => (
                          <tr key={m.device_id} className={m.minutes ? "" : "off"}>
                            <td>{i + 1}</td>
                            <td><b>{m.hostname}</b>{m.deleted && <span className="badge">đã xoá</span>}</td>
                            <td className="num">{m.minutes.toLocaleString("vi-VN")}</td>
                            <td className="num">{gio(m.minutes)}</td>
                            <td className="num">{m.days}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              ))}
            </>
          ) : <p className="muted">Chưa có dữ liệu sử dụng trong kỳ này.</p>}
        </>
      )}
    </>
  );
}

// ====================================================================== theo ngày / tháng + báo cáo một ngày
function SeriesTab({ rooms }: { rooms: Room[] }) {
  const [group, setGroup] = useState<"day" | "month">("day");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [room, setRoom] = useState("");
  const [day, setDay] = useState<string | null>(null);
  const p = new URLSearchParams({ group });
  if (from) p.set("date_from", from);
  if (to) p.set("date_to", to);
  if (room) p.set("room_id", room);
  const qs = p.toString();
  const s = useQuery({
    queryKey: ["reports", "series", qs],
    queryFn: () => getJson<{ items: Point[]; date_from: string; date_to: string }>(`/api/reports/usage/series?${qs}`),
  });
  const items = useMemo(() => s.data?.items ?? [], [s.data]);
  const chart = useMemo(() => ({ labels: items.map((x) => x.period), hours: items.map((x) => gio(x.minutes)) }),
    [items]);
  const pickDay = (period: string) => group === "day" && setDay(period);

  return (
    <>
      <div className="toolbar filters">
        <div className="seg">
          <button className={group === "day" ? "on" : ""} onClick={() => { setGroup("day"); setDay(null); }}>Theo ngày</button>
          <button className={group === "month" ? "on" : ""} onClick={() => { setGroup("month"); setDay(null); }}>
            Theo tháng</button>
        </div>
        <label className="small">Từ <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="small">đến <input type="date" value={to} max={iso(new Date())}
                                            onChange={(e) => setTo(e.target.value)} /></label>
        <RoomSelect rooms={rooms} value={room} onChange={setRoom} />
        {s.data && <span className="muted small">{s.data.date_from} → {s.data.date_to}</span>}
      </div>
      {s.isPending && <p className="muted">Đang tải…</p>}
      {s.isError && <p className="error">{s.error.message}</p>}
      {s.data && (items.length === 0 ? <p className="muted">Chưa có dữ liệu trong khoảng này.</p> : (
        <>
          <HoursChart labels={chart.labels} hours={chart.hours}
                      onPick={(i) => pickDay(items[i].period)} />
          <table className="grid">
            <thead><tr><th>{group === "day" ? "Ngày" : "Tháng"}</th><th className="num">Tổng giờ</th>
              <th className="num">Số máy có dùng</th><th className="num">Giờ TB / máy</th></tr></thead>
            <tbody>
              {[...items].reverse().map((x) => (
                <tr key={x.period} className={group === "day" ? `click${day === x.period ? " sel" : ""}` : ""}
                    onClick={() => pickDay(x.period)}>
                  <td><b>{x.period}</b></td><td className="num">{gio(x.minutes).toLocaleString("vi-VN")}</td>
                  <td className="num">{x.machines}</td><td className="num">{x.machines ? gio(x.minutes / x.machines) : 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {group === "day" && <p className="muted small">Bấm một ngày (cột hoặc dòng) để xem từng máy.</p>}
        </>
      ))}
      {day && <DayReport day={day} room={room} onClose={() => setDay(null)} />}
    </>
  );
}

function DayReport({ day, room, onClose }: { day: string; room: string; onClose: () => void }) {
  const p = new URLSearchParams({ day });
  if (room) p.set("room_id", room);
  const d = useQuery({
    queryKey: ["reports", "day", p.toString()],
    queryFn: () => getJson<{ items: DayRow[]; total: number; minutes: number }>(`/api/reports/usage/day?${p.toString()}`),
  });
  return (
    <div className="rp-day">
      <h2>
        Ngày {day.split("-").reverse().join("/")}
        {d.data && <small className="muted"> — {d.data.total} máy · {gio(d.data.minutes).toLocaleString("vi-VN")} giờ</small>}
        <button className="ghost small" onClick={onClose}>Đóng</button>
      </h2>
      {d.isPending && <p className="muted">Đang tải…</p>}
      {d.isError && <p className="error">{d.error.message}</p>}
      {d.data && (
        <table className="grid">
          <thead><tr><th>Phòng</th><th>Máy</th><th className="num">Phút dùng</th><th>RAM</th><th>RAM đổi lần cuối</th></tr></thead>
          <tbody>
            {d.data.items.map((m) => (
              <tr key={m.device_id}>
                <td>{m.room_name}</td><td><b>{m.hostname}</b></td><td className="num">{m.minutes}</td>
                <td>{m.ram}</td><td className={m.ram_changed_at ? "err-text" : "muted"}>{fmtTime(m.ram_changed_at) || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ====================================================================== lịch sử RAM / ổ cứng
function HardwareTab() {
  const [q, setQ] = useState("");
  const p = new URLSearchParams({ limit: "1000" });
  if (q.trim()) p.set("q", q.trim());
  const h = useQuery({
    queryKey: ["reports", "hw", p.toString()],
    queryFn: () => getJson<ListResult<HwRow>>(`/api/reports/hardware-history?${p.toString()}`),
  });
  return (
    <>
      <p className="muted small">Thay đổi RAM / ổ cứng do hệ thống tự phát hiện từ nhịp tim (thêm, mất, tráo). Xử lý
        phiếu ở trang Sự cố.</p>
      <div className="toolbar filters">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm máy / phòng…" maxLength={64} />
        {h.data && <span className="muted small">{h.data.total} lần thay đổi</span>}
      </div>
      {h.isPending && <p className="muted">Đang tải…</p>}
      {h.isError && <p className="error">{h.error.message}</p>}
      {h.data && (h.data.items.length === 0 ? <p className="muted">Chưa ghi nhận thay đổi phần cứng nào.</p> : (
        <table className="grid">
          <thead><tr><th>Thời gian</th><th>Máy</th><th>Phòng</th><th>MAC</th><th>Bộ phận</th><th>Thay đổi</th>
            <th>Trước</th><th>Sau</th><th>Phiếu</th></tr></thead>
          <tbody>
            {h.data.items.map((r) => (
              <tr key={r.id}>
                <td>{fmtTime(r.created_at)}</td><td><b>{r.hostname}</b></td><td>{r.room_name}</td><td>{r.mac}</td>
                <td>{r.part}</td><td className="err-text">{r.event_type}</td><td className="small">{r.old_value}</td>
                <td className="small">{r.new_value}</td>
                <td><span className={`st st-${r.status}`}>{r.status === "DONE" ? "Đã xử lý" : "Chưa xử lý"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </>
  );
}
