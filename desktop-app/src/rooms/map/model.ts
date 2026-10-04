// Mô hình sơ đồ phòng (Sổ tay 5.3) — kiểu sinh từ Core (MapModel của app/rooms/maps.py). Toạ độ cùng hệ px với trình
// vẽ của hệ cũ (nền 1000×1300, máy 85×95) để tệp xuất cho hệ thi khớp từng điểm.
import type { components } from "../../api-client/schema";

export type MapItem = components["schemas"]["MapModel.MapItem"];
export type Rect = components["schemas"]["MapModel.Rect"];
export type MapData = { v: 1; canvas_w: number; bounds: Rect; items: MapItem[] };
export type Kind = MapItem["kind"];
export type Dir = MapItem["dir"];

export type MapResponse = {
  room_id: string;
  room_name: string;
  map: MapData | null;
  source: "core" | "legacy" | null;
  updated_at: string | null;
  updated_by: string | null;
  can_edit: boolean;
};

// Lưới của hệ cũ (room_detail.html mapColToX/mapRowToY): 2 máy một bàn cách 20, giữa 2 bàn 80, hàng cách 22, gốc 90
export const PC_W = 85, PC_H = 95, DOOR_W = 40, DOOR_H = 80;
const GAP_IN = 20, GAP_DESK = 80, GAP_ROW = 22, START = 90, DESK_W = 2 * PC_W + GAP_IN;
export const colToX = (c: number) => START + Math.floor(c / 2) * (DESK_W + GAP_DESK) + (c % 2) * (PC_W + GAP_IN);
export const rowToY = (r: number) => START + r * (PC_H + GAP_ROW);
export const SNAP_X = Array.from({ length: 30 }, (_, i) => colToX(i));
export const SNAP_Y = Array.from({ length: 60 }, (_, i) => rowToY(i));

/** Hít vào mốc lưới gần nhất trong ngưỡng (như snapToGrid cũ, 30px); ngoài ngưỡng → giữ nguyên. */
export function snap(v: number, marks: number[], thr = 30): number {
  let best = v;
  let bd = thr;
  for (const m of marks) {
    const d = Math.abs(v - m);
    if (d <= bd) {
      bd = d;
      best = m;
    }
  }
  return best;
}

export function emptyMap(): MapData {
  return { v: 1, canvas_w: 1000, bounds: { x: 40, y: 0, w: 920, h: 1300 }, items: defaultDoors(1300) };
}

export function defaultDoors(boundsH: number): MapItem[] {
  return [1, 2, 3, 4].map((pos) => blank("door", `door-${pos}`, { pos, y: pos % 2 ? 80 : boundsH - 185 - DOOR_H }));
}

/** Phần tử mới đủ mọi trường (Core trả model_dump đầy đủ — giữ cùng hình dạng để so "có đổi chưa"). */
export function blank(kind: Kind, id: string, p: Partial<MapItem> = {}): MapItem {
  return {
    id, kind, x: 0, y: 0, w: null, h: null, seat: null, dir: "", pos: null, decor: null, label: null, group: null,
    gname: null, code: null, monitor_code: null, case_code: null, html: null, ...p,
  };
}

export function normalize(m: Partial<MapData> & { items?: MapItem[] }): MapData {
  return {
    v: 1, canvas_w: m.canvas_w ?? 1000, bounds: m.bounds ?? { x: 40, y: 0, w: 920, h: 1300 }, items: m.items ?? [],
  };
}

/** Hình chữ nhật của phần tử trong toạ độ nền. Cửa nằm NGOÀI viền phòng (swing-out ±43px) như hệ cũ. */
export function rectOf(it: MapItem, m: MapData): { x: number; y: number; w: number; h: number } {
  if (it.kind === "door") {
    const left = (it.pos ?? 1) <= 2;
    return { x: left ? m.bounds.x - 43 : m.bounds.x + m.bounds.w + 3, y: m.bounds.y + it.y, w: DOOR_W, h: DOOR_H };
  }
  const w = it.w ?? (it.kind === "pc" || it.kind === "gv" ? PC_W : 60);
  const h = it.h ?? (it.kind === "pc" || it.kind === "gv" ? PC_H : 60);
  return { x: it.x, y: it.y, w, h };
}

/** Khớp chữ trên thẻ ("40") với tên máy thật ("A6-702-40") — GIỐNG mapFindHost của hệ thi (sodo.js). */
export function findHost(name: string | null | undefined, hosts: string[]): string | null {
  const n = String(name ?? "").trim();
  if (!n) return null;
  let hit = hosts.filter((h) => h.toUpperCase() === n.toUpperCase());
  if (hit.length !== 1) hit = hosts.filter((h) => h.toUpperCase().endsWith("-" + n.toUpperCase()));
  if (hit.length !== 1) {
    const e = n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp("(^|[^0-9])" + e + "([^0-9]|$)");
    hit = hosts.filter((h) => re.test(h));
  }
  return hit.length === 1 ? hit[0] : null;
}

export function groupColor(gid: string): string {
  let h = 0;
  for (let i = 0; i < gid.length; i++) h = (h * 31 + gid.charCodeAt(i)) >>> 0;
  return `hsl(${h % 360}, 72%, 45%)`;
}

export const DIR_NEXT: Record<string, Dir> = {
  "": "dir-col", "dir-col": "dir-row", "dir-row": "dir-col-rev", "dir-col-rev": "dir-row-rev", "dir-row-rev": "",
};
export const DIR_ARROW: Record<string, string> = {
  "": "", "dir-col": "↑", "dir-row": "→", "dir-col-rev": "↓", "dir-row-rev": "←",
};

export type DecorKind = NonNullable<MapItem["decor"]>;
export const DECOR: Record<DecorKind, { icon: string; label: string; w: number; h: number }> = {
  "y-te": { icon: "➕", label: "Y Tế", w: 60, h: 60 },
  "cuu-hoa": { icon: "🧯", label: "PCCC", w: 60, h: 90 },
  "ke-giay": { icon: "👟", label: "Kệ Giày", w: 60, h: 180 },
  "tu-do": { icon: "🗄️", label: "Tủ Đồ", w: 60, h: 180 },
  "tu-rack": { icon: "🖧", label: "Tủ Rack", w: 85, h: 85 },
};

export function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/** Sơ đồ tự động từ danh sách máy (phòng chưa có sơ đồ): 6 máy một hàng như tệp Excel mẫu của hệ cũ, số lớn trên. */
export function autoLayout(hosts: string[]): MapData {
  const seatOf = (h: string) => (h.match(/(\d+)\s*$/)?.[1] ?? h).padStart(2, "0");
  const gv = hosts.filter((h) => /gv$/i.test(h.replace(/[^a-z0-9]/gi, "")));
  const pcs = hosts.filter((h) => !gv.includes(h)).map(seatOf).sort((a, b) => Number(b) - Number(a) || b.localeCompare(a));
  const COLS = 6;
  const rows = Math.max(1, Math.ceil(pcs.length / COLS));
  const items = pcs.map((seat, i) => blank("pc", `pc-${seat}`, {
    seat, x: colToX(i % COLS), y: rowToY(Math.floor(i / COLS)), w: PC_W, h: PC_H,
  }));
  const h = Math.max(1300, rowToY(rows - 1) + PC_H + 300);
  if (gv.length) items.push(blank("gv", uid("item-desk"), { seat: "GV", x: 680, y: rowToY(rows) + 40, w: 215, h: 108 }));
  return { v: 1, canvas_w: 1000, bounds: { x: 40, y: 0, w: 920, h }, items: [...items, ...defaultDoors(h)] };
}
