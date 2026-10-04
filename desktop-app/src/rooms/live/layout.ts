// Vị trí card trên lưới View desktop (Sổ tay 5.4) — đơn vị Ô LƯỚI {fx, fy} như hệ cũ (độc lập cỡ card).
// Thứ tự ưu tiên: bố trí đã lưu (rooms.live_layout, khoá = TÊN MÁY HOA) → mirror sơ đồ phòng (gom hàng/cột theo tâm thẻ
// máy, như `_axis` của room_detail.html) → lưới theo số ghế. Máy chưa có chỗ xếp nối phía dưới, không bao giờ bị nuốt.
import type { Device } from "../../api-client/types";
import { seatNo } from "../../shared/metrics";
import { findHost, rectOf, type MapData } from "../map/model";

export type Cell = { fx: number; fy: number };

/** Gom các toạ độ gần nhau (≤ thr px) thành một cột/hàng; trả hàm đổi toạ độ → chỉ số 0..n-1. */
function axis(vals: number[], thr = 45): (v: number) => number {
  const centers: number[] = [];
  for (const v of [...vals].sort((a, b) => a - b)) {
    const last = centers[centers.length - 1];
    if (last === undefined || v - last > thr) centers.push(v);
  }
  return (v) => {
    let best = 0;
    for (let i = 1; i < centers.length; i++) if (Math.abs(centers[i] - v) < Math.abs(centers[best] - v)) best = i;
    return best;
  };
}

export function layoutCells(devices: Device[], saved: Record<string, Cell>, map: MapData | null): Map<string, Cell> {
  const out = new Map<string, Cell>();
  const key = (d: Device) => d.hostname.toUpperCase();
  const taken = new Set<string>();
  const put = (k: string, c: Cell) => {
    let fx = c.fx;
    while (taken.has(`${fx},${c.fy}`)) fx += 1; // hai máy rơi cùng ô → đẩy sang phải, không chồng nhau
    taken.add(`${fx},${c.fy}`);
    out.set(k, { fx, fy: c.fy });
  };
  if (Object.keys(saved).length) {
    for (const d of devices) {
      const p = saved[key(d)];
      if (p) put(key(d), p);
    }
  } else if (map) {
    const hosts = devices.map((d) => d.hostname);
    const centers = new Map<string, { x: number; y: number }>();
    for (const it of map.items) {
      if (it.kind !== "pc" && it.kind !== "gv") continue;
      const h = findHost(it.seat, hosts);
      if (!h) continue;
      const r = rectOf(it, map);
      centers.set(h.toUpperCase(), { x: r.x + r.w / 2, y: r.y + r.h / 2 });
    }
    if (centers.size >= Math.max(1, devices.length * 0.6)) {
      const ax = axis([...centers.values()].map((c) => c.x));
      const ay = axis([...centers.values()].map((c) => c.y));
      const order = [...centers.entries()].sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x);
      for (const [k, c] of order) put(k, { fx: ax(c.x), fy: ay(c.y) });
    }
  }
  const rest = devices.filter((d) => !out.has(key(d)))
    .sort((a, b) => seatNo(a.hostname) - seatNo(b.hostname) || a.hostname.localeCompare(b.hostname));
  if (rest.length) {
    const cols = Math.max(8, ...[...out.values()].map((c) => Math.floor(c.fx) + 1));
    const top = out.size ? Math.max(...[...out.values()].map((c) => Math.ceil(c.fy))) + 1 : 0;
    rest.forEach((d, i) => put(key(d), { fx: i % cols, fy: top + Math.floor(i / cols) }));
  }
  return out;
}
