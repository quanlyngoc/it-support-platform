// View desktop (Sổ tay 5.4, kiểu NetSupport): mỗi máy một ảnh màn hình đang chạy (lấy từ stream winvnc của agent qua
// `vnc_thumb_req` → `vnc_thumb`, ảnh về ĐÚNG người hỏi), card 16:9 xếp theo sơ đồ phòng; rê chuột giữ 1,2 s → khung HD;
// bấm đúp → cửa sổ điều khiển (noVNC). Người có quyền sửa sơ đồ kéo card để đổi bố trí, lưu cho mọi người cùng thấy.
// Bài học hệ cũ: hỏi ảnh rải 25 ms/máy (không dồn cục); ảnh < 800 B coi như hỏng → GIỮ ảnh cũ (không nháy đen);
// máy offline không hỏi; tab ẩn thì dừng hỏi (không tốn CPU máy trạm).
import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../api-client";
import type { Device, RoomDetail } from "../../api-client/types";
import { openVnc } from "../../devices/vnc";
import { realtime, request, useRealtime } from "../../realtime-client";
import { isGV } from "../../shared/metrics";
import type { MapData } from "../map/model";
import { layoutCells, type Cell } from "./layout";

type Thumb = { hostname: string; image: string; hd?: boolean };
const GAP = 10;
const POLL_MS = 1500;
const HD_MS = 1000;
const HOVER_MS = 1200;

export function LiveGrid({ room, map, canEdit, onOpenDevice }: {
  room: RoomDetail; map: MapData | null; canEdit: boolean; onOpenDevice: (id: string) => void;
}) {
  const qc = useQueryClient();
  const connected = useRealtime((s) => s.connected);
  const thumbs = useRef(new Map<string, string>());
  const hdCache = useRef(new Map<string, { url: string; at: number }>()); // HD xin trước lúc chuột vừa vào card
  const [, bump] = useState(0);
  const [hd, setHd] = useState<{ dev: Device; url: string | null } | null>(null);
  const hdRef = useRef(hd);
  hdRef.current = hd;
  const hoverT = useRef<number | undefined>(undefined);
  const [width, setWidth] = useState(1000);
  const [wrapEl, setWrapEl] = useState<HTMLDivElement | null>(null);
  const [edit, setEdit] = useState<Record<string, Cell> | null>(null);
  const [drag, setDrag] = useState<{ host: string; x: number; y: number } | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const devices = room.devices;

  useEffect(() => {
    if (!wrapEl) return;
    const ro = new ResizeObserver(() => setWidth(wrapEl.clientWidth));
    ro.observe(wrapEl);
    setWidth(wrapEl.clientWidth);
    return () => ro.disconnect();
  }, [wrapEl]);

  // Ảnh về (chỉ cho chính phiên này — Core gắn reply_sid) + bố trí đổi do người khác lưu
  useEffect(() => {
    const s = realtime();
    if (!s || !connected) return;
    const onThumb = (p: Thumb) => {
      if (!p?.image || p.image.length < 800) return; // ảnh hỏng → giữ ảnh cũ
      const host = String(p.hostname || "").toUpperCase();
      const url = `data:image/jpeg;base64,${p.image}`;
      if (p.hd) {
        hdCache.current.set(host, { url, at: Date.now() });
        setHd((cur) => (cur && cur.dev.hostname.toUpperCase() === host ? { ...cur, url } : cur));
      } else {
        thumbs.current.set(host, url);
        bump((n) => n + 1);
      }
    };
    const onLayout = (p: { room_id: string; what?: string }) => {
      if (p.room_id === room.id && p.what === "live_layout") void qc.invalidateQueries({ queryKey: ["room", room.id] });
    };
    s.on("vnc_thumb", onThumb);
    s.on("room_map_updated", onLayout);
    return () => {
      s.off("vnc_thumb", onThumb);
      s.off("room_map_updated", onLayout);
    };
  }, [connected, qc, room.id]);

  // Hỏi ảnh nhỏ cho mọi máy đang online, rải 25 ms/máy; tab ẩn thì thôi
  const onlineIds = devices.filter((d) => d.is_online).map((d) => d.id).join(",");
  useEffect(() => {
    if (!connected || !onlineIds) return;
    const ids = onlineIds.split(",");
    let timers: number[] = [];
    const tick = () => {
      if (document.hidden) return;
      timers = ids.map((id, i) => window.setTimeout(() => void request("vnc_thumb_req", { device_id: id }), i * 25));
    };
    tick();
    const t = window.setInterval(tick, POLL_MS);
    return () => {
      clearInterval(t);
      timers.forEach(clearTimeout);
    };
  }, [connected, onlineIds]);

  // Khung HD: chỉ máy đang mở khung mới xin ảnh HD (máy khác không tốn)
  const hdId = hd?.dev.id;
  useEffect(() => {
    if (!hdId || !connected) return;
    const ask = () => void request("vnc_thumb_req", { device_id: hdId, hd: true });
    ask();
    const t = window.setInterval(ask, HD_MS);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setHd(null);
    window.addEventListener("keydown", esc);
    return () => {
      clearInterval(t);
      window.removeEventListener("keydown", esc);
    };
  }, [hdId, connected]);

  const cells = useMemo(() => layoutCells(devices, (edit ?? room.live_layout) as Record<string, Cell>, map),
    [devices, edit, room.live_layout, map]);
  const nCols = Math.max(1, ...[...cells.values()].map((c) => Math.floor(c.fx) + 1));
  const nRows = Math.max(1, ...[...cells.values()].map((c) => Math.floor(c.fy) + 1));
  const cardW = Math.max(150, Math.min(420, (width - 24 - GAP * (nCols - 1)) / nCols));
  const cardH = Math.round(cardW * 9 / 16) + 26;
  const stepX = cardW + GAP;
  const stepY = cardH + GAP;

  async function vnc(d: Device) {
    setMsg(null);
    try {
      await openVnc(d);
    } catch (e) {
      setMsg({ kind: "err", text: (e as Error).message });
    }
  }

  // ---- sửa bố trí: kéo card, thả thì hít vào ô (bàn GV đặt tự do theo bước 0,25 ô như hệ cũ)
  function startDrag(e: RPointerEvent, d: Device) {
    if (!edit || e.button !== 0) return;
    e.preventDefault();
    const host = d.hostname.toUpperCase();
    const c = cells.get(host) ?? { fx: 0, fy: 0 };
    const ox = e.clientX - c.fx * stepX;
    const oy = e.clientY - c.fy * stepY;
    setDrag({ host, x: c.fx * stepX, y: c.fy * stepY });
    const mv = (ev: PointerEvent) => setDrag({ host, x: ev.clientX - ox, y: ev.clientY - oy });
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", mv);
      window.removeEventListener("pointerup", up);
      const step = isGV(host) ? 0.25 : 1;
      const fx = Math.max(0, Math.round((ev.clientX - ox) / stepX / step) * step);
      const fy = Math.max(0, Math.round((ev.clientY - oy) / stepY / step) * step);
      const next: Record<string, Cell> = {};
      for (const [k, v] of cells) next[k] = v;
      const other = [...cells.entries()].find(([k, v]) => k !== host && v.fx === fx && v.fy === fy);
      if (other) next[other[0]] = c; // thả vào ô đã có máy → đổi chỗ hai máy
      next[host] = { fx, fy };
      setEdit(next);
      setDrag(null);
    };
    window.addEventListener("pointermove", mv);
    window.addEventListener("pointerup", up);
  }

  async function saveLayout(layout: Record<string, Cell>) {
    const r = await api().PUT("/api/rooms/{room_id}/live-layout", {
      params: { path: { room_id: room.id } }, body: { layout },
    });
    if (!r.response.ok) return setMsg({ kind: "err", text: errorMessage(r.error) });
    setEdit(null);
    void qc.invalidateQueries({ queryKey: ["room", room.id] });
    setMsg({ kind: "ok", text: Object.keys(layout).length ? "Đã lưu bố trí — mọi người xem phòng này thấy giống nhau."
      : "Đã trả bố trí về theo sơ đồ phòng." });
  }

  const enter = (d: Device) => {
    if (edit || !d.is_online) return;
    void request("vnc_thumb_req", { device_id: d.id, hd: true }); // xin HD TRƯỚC → bung khung là nét luôn
    window.clearTimeout(hoverT.current);
    hoverT.current = window.setTimeout(() => {
      const c = hdCache.current.get(d.hostname.toUpperCase());
      setHd({ dev: d, url: c && Date.now() - c.at < 5000 ? c.url : null });
    }, HOVER_MS);
  };
  const leave = () => window.clearTimeout(hoverT.current);

  return (
    <div className="live-view">
      <div className="map-toolbar">
        <span className="muted small">
          Rê chuột giữ 1 giây trên một máy để xem nét · bấm đúp để điều khiển
          {!connected && " · đang mất kết nối máy chủ, ảnh tạm dừng"}
        </span>
        {canEdit && (edit ? (
          <span className="live-edit-btns">
            <button onClick={() => void saveLayout(edit)}>Lưu bố trí</button>
            <button className="ghost" onClick={() => void saveLayout({})} title="Xoá bố trí đã lưu, xếp theo sơ đồ phòng">
              Theo sơ đồ
            </button>
            <button className="ghost" onClick={() => setEdit(null)}>Huỷ</button>
          </span>
        ) : (
          <button className="ghost small" onClick={() => setEdit(Object.fromEntries(cells))}>Sửa bố trí</button>
        ))}
      </div>
      {msg && <p className={msg.kind === "ok" ? "notice" : "error"}>{msg.text}</p>}
      <div className="live-wrap" ref={setWrapEl}>
        <div className={`live-canvas${edit ? " editing" : ""}`} style={{ height: nRows * stepY + 4, width: nCols * stepX }}>
          {devices.map((d) => {
            const host = d.hostname.toUpperCase();
            const c = cells.get(host) ?? { fx: 0, fy: 0 };
            const dragging = drag?.host === host;
            const img = thumbs.current.get(host);
            return (
              <div key={d.id} className={`lc${d.is_online ? "" : " off"}${dragging ? " drag" : ""}${isGV(host) ? " gv" : ""}`}
                   style={{ left: dragging ? drag.x : c.fx * stepX, top: dragging ? drag.y : c.fy * stepY, width: cardW,
                            height: cardH }}
                   onPointerDown={(e) => startDrag(e, d)} onMouseEnter={() => enter(d)} onMouseLeave={leave}
                   onDoubleClick={() => !edit && d.is_online && void vnc(d)}
                   title={`${d.hostname} — ${d.is_online ? "Online" : "Offline"}`}>
                <div className="lc-shot">
                  {img && d.is_online ? <img src={img} alt="" draggable={false} />
                    : <span>{d.is_online ? "Đang lấy ảnh…" : "Offline"}</span>}
                  <b className="lc-name">{d.hostname}</b>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {hd && (
        <div className="live-hd" onMouseDown={(e) => e.target === e.currentTarget && setHd(null)}>
          <div className="live-hd-box" role="dialog" aria-label={`Màn hình ${hd.dev.hostname}`}>
            <div className="live-hd-bar">
              <b>{hd.dev.hostname}</b>
              <span className="muted small">{hd.url ? "ảnh HD" : "đang lấy ảnh HD…"}</span>
              <span className="grow" />
              <button onClick={() => void vnc(hd.dev)}>Điều khiển</button>
              <button className="ghost" onClick={() => onOpenDevice(hd.dev.id)}>Chi tiết máy</button>
              <button className="ghost" onClick={() => setHd(null)}>Đóng</button>
            </div>
            {hd.url /* KHÔNG phóng ảnh nhỏ cho đỡ trống — mờ, người xem tưởng lỗi (bài học hệ cũ) */
              ? <img src={hd.url} alt="" onDoubleClick={() => void vnc(hd.dev)} />
              : <div className="live-hd-wait">Đang lấy ảnh HD…</div>}
          </div>
        </div>
      )}
    </div>
  );
}
