// Vẽ sơ đồ + thao tác chuột (Sổ tay 5.3). XEM: thẻ máy tô theo trạng thái thật; bấm → chi tiết máy, Ctrl+bấm → chọn
// máy (Chuyển phòng). SỬA: kéo 1/nhiều phần tử (hít lưới như hệ cũ, giữ Alt = đặt tự do), khoanh vùng để chọn,
// Ctrl/Shift thêm-bớt, kéo góc để đổi cỡ, kéo góc viền phòng để đổi cỡ phòng. Cửa chỉ trượt dọc theo tường.
// Toạ độ luôn tính trong hệ px của nền (không phụ thuộc mức phóng) → lưu ra đúng toạ độ hệ cũ / hệ thi.
import { useRef, useState, type CSSProperties, type MouseEvent as RMouseEvent, type PointerEvent as RPointerEvent } from "react";
import type { Device } from "../../api-client/types";
import {
  DECOR, DIR_ARROW, DOOR_H, findHost, groupColor, rectOf, SNAP_X, SNAP_Y, snap, type MapData, type MapItem,
} from "./model";

type Box = { x: number; y: number; w: number; h: number };
type Gesture =
  | { kind: "move"; sx: number; sy: number; before: MapData; orig: Map<string, MapItem>; primary: string; moved: boolean }
  | { kind: "resize"; sx: number; sy: number; before: MapData; id: string; w0: number; h0: number; moved: boolean }
  | { kind: "bounds"; sx: number; sy: number; before: MapData; w0: number; h0: number; moved: boolean }
  | { kind: "band"; sx: number; sy: number; add: boolean; base: Set<string> };

export type CanvasProps = {
  map: MapData;
  roomName: string;
  editing: boolean;
  scale: number;
  hosts: string[];
  devByHost: Map<string, Device>;
  sel: Set<string>;
  devSel: Set<string>;
  onSel: (s: Set<string>) => void;
  onLive: (m: MapData) => void; // đổi tức thì trong lúc kéo (chưa ghi lịch sử)
  onCommit: (before: MapData) => void; // xong một thao tác → lịch sử hoàn tác
  onOpenDevice: (id: string) => void;
  onToggleDevice: (id: string) => void;
};

/** Lề trái để cửa tường trái (nhô ra ngoài viền phòng 43px) không bị cắt — chỉ dời KHI VẼ, toạ độ lưu giữ nguyên. */
export const leftPad = (m: MapData) => Math.max(0, 55 - m.bounds.x);

export function stageSize(m: MapData): { w: number; h: number } {
  let w = Math.max(m.canvas_w, m.bounds.x + m.bounds.w + 60) + leftPad(m);
  let h = m.bounds.y + m.bounds.h + 20;
  for (const it of m.items) {
    const r = rectOf(it, m);
    w = Math.max(w, r.x + r.w + 20 + leftPad(m));
    h = Math.max(h, r.y + r.h + 20);
  }
  return { w, h };
}

const hit = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export function MapCanvas(p: CanvasProps) {
  const { map, editing, scale } = p;
  const stage = useRef<HTMLDivElement>(null);
  const g = useRef<Gesture | null>(null);
  const [band, setBand] = useState<Box | null>(null);
  const size = stageSize(map);
  const pad = leftPad(map);

  const toCanvas = (cx: number, cy: number) => {
    const r = stage.current?.getBoundingClientRect();
    return { x: (cx - (r?.left ?? 0)) / scale - pad, y: (cy - (r?.top ?? 0)) / scale };
  };

  function track(onMove: (e: PointerEvent) => void, onUp: (e: PointerEvent) => void) {
    const mv = (e: PointerEvent) => onMove(e);
    const up = (e: PointerEvent) => {
      window.removeEventListener("pointermove", mv);
      window.removeEventListener("pointerup", up);
      onUp(e);
      g.current = null;
    };
    window.addEventListener("pointermove", mv);
    window.addEventListener("pointerup", up);
  }

  // ---- kéo phần tử (1 hoặc nhiều)
  function startMove(e: RPointerEvent, it: MapItem) {
    if (!editing || e.button !== 0) return;
    e.stopPropagation();
    let sel = p.sel;
    if (e.ctrlKey || e.metaKey || e.shiftKey) {
      sel = new Set(sel);
      if (sel.has(it.id)) sel.delete(it.id);
      else sel.add(it.id);
      p.onSel(sel);
      return;
    }
    if (!sel.has(it.id)) {
      sel = new Set([it.id]);
      p.onSel(sel);
    }
    const orig = new Map(map.items.filter((x) => sel.has(x.id)).map((x) => [x.id, x]));
    const pt = toCanvas(e.clientX, e.clientY);
    g.current = { kind: "move", sx: pt.x, sy: pt.y, before: map, orig, primary: it.id, moved: false };
    track((ev) => {
      const s = g.current;
      if (!s || s.kind !== "move") return;
      const q = toCanvas(ev.clientX, ev.clientY);
      let dx = q.x - s.sx;
      let dy = q.y - s.sy;
      if (!s.moved && Math.abs(dx) < 2 && Math.abs(dy) < 2) return;
      s.moved = true;
      const pr = s.orig.get(s.primary);
      if (pr && !ev.altKey && pr.kind !== "door") { // hít lưới theo phần tử đang cầm, cả cụm dời cùng một khoảng
        dx = snap(pr.x + dx, SNAP_X) - pr.x;
        dy = snap(pr.y + dy, SNAP_Y) - pr.y;
      }
      const items = s.before.items.map((x) => {
        const o = s.orig.get(x.id);
        if (!o) return x;
        if (o.kind === "door") {
          return { ...o, y: Math.round(Math.min(Math.max(0, o.y + dy), s.before.bounds.h - DOOR_H)) };
        }
        return { ...o, x: Math.round((o.x + dx) * 10) / 10, y: Math.round((o.y + dy) * 10) / 10 };
      });
      p.onLive({ ...s.before, items });
    }, () => {
      const s = g.current;
      if (s && s.kind === "move" && s.moved) p.onCommit(s.before);
    });
  }

  // ---- đổi cỡ 1 phần tử
  function startResize(e: RPointerEvent, it: MapItem) {
    e.stopPropagation();
    const r = rectOf(it, map);
    const pt = toCanvas(e.clientX, e.clientY);
    g.current = { kind: "resize", sx: pt.x, sy: pt.y, before: map, id: it.id, w0: r.w, h0: r.h, moved: false };
    track((ev) => {
      const s = g.current;
      if (!s || s.kind !== "resize") return;
      const q = toCanvas(ev.clientX, ev.clientY);
      s.moved = true;
      const w = Math.max(20, Math.round(s.w0 + q.x - s.sx));
      const h = Math.max(20, Math.round(s.h0 + q.y - s.sy));
      p.onLive({ ...s.before, items: s.before.items.map((x) => (x.id === s.id ? { ...x, w, h } : x)) });
    }, () => {
      const s = g.current;
      if (s && s.kind === "resize" && s.moved) p.onCommit(s.before);
    });
  }

  // ---- đổi cỡ viền phòng
  function startBounds(e: RPointerEvent) {
    e.stopPropagation();
    const pt = toCanvas(e.clientX, e.clientY);
    g.current = { kind: "bounds", sx: pt.x, sy: pt.y, before: map, w0: map.bounds.w, h0: map.bounds.h, moved: false };
    track((ev) => {
      const s = g.current;
      if (!s || s.kind !== "bounds") return;
      const q = toCanvas(ev.clientX, ev.clientY);
      s.moved = true;
      const w = Math.max(300, Math.round(s.w0 + q.x - s.sx));
      const h = Math.max(300, Math.round(s.h0 + q.y - s.sy));
      const b = { ...s.before.bounds, w, h };
      p.onLive({ ...s.before, bounds: b, canvas_w: Math.max(s.before.canvas_w, b.x + w) });
    }, () => {
      const s = g.current;
      if (s && s.kind === "bounds" && s.moved) p.onCommit(s.before);
    });
  }

  // ---- khoanh vùng để chọn
  function startBand(e: RPointerEvent) {
    if (!editing || e.button !== 0) return;
    const pt = toCanvas(e.clientX, e.clientY);
    const add = e.ctrlKey || e.metaKey || e.shiftKey;
    g.current = { kind: "band", sx: pt.x, sy: pt.y, add, base: add ? new Set(p.sel) : new Set() };
    if (!add) p.onSel(new Set());
    track((ev) => {
      const s = g.current;
      if (!s || s.kind !== "band") return;
      const q = toCanvas(ev.clientX, ev.clientY);
      const b = { x: Math.min(s.sx, q.x), y: Math.min(s.sy, q.y), w: Math.abs(q.x - s.sx), h: Math.abs(q.y - s.sy) };
      setBand(b);
      const next = new Set(s.base);
      for (const it of map.items) if (hit(b, rectOf(it, map))) next.add(it.id);
      p.onSel(next);
    }, () => setBand(null));
  }

  // ---- nhãn cụm: đặt trên máy trên-cùng-trái nhất (như refreshGroupVisuals cũ)
  const groups = new Map<string, { name: string; at: MapItem }>();
  for (const it of map.items) {
    if (!it.group) continue;
    const cur = groups.get(it.group);
    if (!cur || it.y * 100000 + it.x < cur.at.y * 100000 + cur.at.x) groups.set(it.group, { name: it.gname ?? "", at: it });
  }
  const single = editing && p.sel.size === 1 ? map.items.find((x) => p.sel.has(x.id) && x.kind !== "door") : undefined;
  const b = map.bounds;

  return (
    <div className={`map-stage${editing ? " editing" : ""}`} style={{ width: size.w * scale, height: size.h * scale }}>
      <div ref={stage} className="map-canvas" style={{ width: size.w, height: size.h, transform: `scale(${scale})` }}
           onPointerDown={startBand}>
        <div className="map-origin" style={{ left: pad }}>
        <div className="map-bounds" style={{ left: b.x, top: b.y, width: b.w, height: b.h }}>
          <span className="map-title">SƠ ĐỒ {p.roomName.toUpperCase()}</span>
          {editing && <i className="map-handle bounds" onPointerDown={startBounds} title="Kéo để đổi cỡ phòng" />}
        </div>
        {map.items.map((it) => (
          <Item key={it.id} it={it} map={map} editing={editing} selected={p.sel.has(it.id)} hosts={p.hosts}
                devByHost={p.devByHost} devSel={p.devSel} onDown={(e) => startMove(e, it)}
                onOpenDevice={p.onOpenDevice} onToggleDevice={p.onToggleDevice} />
        ))}
        {[...groups].map(([gid, gr]) => gr.name && (
          <span key={gid} className="map-glabel" style={{ left: gr.at.x - 3, top: gr.at.y - 18, background: groupColor(gid) }}>
            {gr.name}
          </span>
        ))}
        {single && (() => {
          const r = rectOf(single, map);
          return <i className="map-handle" style={{ left: r.x + r.w - 7, top: r.y + r.h - 7 }}
                    onPointerDown={(e) => startResize(e, single)} title="Kéo để đổi cỡ" />;
        })()}
        {band && <div className="map-band" style={{ left: band.x, top: band.y, width: band.w, height: band.h }} />}
        </div>
      </div>
    </div>
  );
}

function Item({ it, map, editing, selected, hosts, devByHost, devSel, onDown, onOpenDevice, onToggleDevice }: {
  it: MapItem; map: MapData; editing: boolean; selected: boolean; hosts: string[]; devByHost: Map<string, Device>;
  devSel: Set<string>; onDown: (e: RPointerEvent) => void; onOpenDevice: (id: string) => void;
  onToggleDevice: (id: string) => void;
}) {
  const r = rectOf(it, map);
  const style: CSSProperties = { left: r.x, top: r.y, width: r.w, height: r.h };
  if (it.group) style.boxShadow = `0 0 0 3px ${groupColor(it.group)}`;
  const cls = `map-it k-${it.kind}${selected ? " sel" : ""}`;

  if (it.kind === "pc" || it.kind === "gv") {
    const host = findHost(it.seat, hosts);
    const d = host ? devByHost.get(host.toUpperCase()) : undefined;
    const st = !d ? "none" : !d.is_online ? "off" : d.channel === "http" ? "http" : "on";
    const tip = d
      ? `${d.hostname} — ${d.is_online ? "Online" : "Offline"}` +
        (d.is_online && d.cpu_usage !== undefined ? ` · CPU ${d.cpu_usage}% · RAM ${d.ram_usage ?? "?"}%` : "")
      : `${it.seat ?? ""} — chưa khớp máy nào`;
    const click = (e: RMouseEvent) => {
      if (editing || !d) return;
      if (e.ctrlKey || e.metaKey || e.shiftKey) onToggleDevice(d.id);
      else onOpenDevice(d.id);
    };
    return (
      <div className={`${cls} st-${st}${d && devSel.has(d.id) ? " dsel" : ""}`} style={style} title={tip}
           onPointerDown={onDown} onClick={click}>
        <span className="pc-ico">🖥️</span>
        <span className="pc-seat">{it.seat}</span>
        {it.dir && <span className="pc-dir">{DIR_ARROW[it.dir]}</span>}
      </div>
    );
  }
  if (it.kind === "door") return <div className={cls} style={style} onPointerDown={onDown} title={`Cửa ${it.pos}`} />;
  if (it.kind === "board") return <div className={cls} style={style} onPointerDown={onDown}>{it.label || "BẢNG KÍNH"}</div>;
  if (it.kind === "decor" && it.decor) {
    const dc = DECOR[it.decor];
    return (
      <div className={`${cls} d-${it.decor}`} style={style} onPointerDown={onDown} title={it.code ?? undefined}>
        <span>{dc?.icon}</span><small>{it.label || dc?.label}</small>
      </div>
    );
  }
  if (it.kind === "ban-sv") return <div className={cls} style={style} onPointerDown={onDown}>{it.label}</div>;
  return <div className={cls} style={style} onPointerDown={onDown} title="Phần tử của trình vẽ cũ (giữ nguyên)">?</div>;
}
