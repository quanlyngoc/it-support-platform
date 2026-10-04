// Sơ đồ phòng (Sổ tay 5.3): xem trạng thái máy trên sơ đồ + trình sửa (quyền room_map.edit) — phóng/thu, kéo, đổi cỡ,
// nhóm có tên, xoay hướng, hoàn tác/làm lại, nhập/xuất Excel, lưu. Lưu thì Core ghi rooms.map VÀ xuất tệp định dạng
// cũ cho hệ thi (ThiHSK/ThiPM). Phòng chưa có sơ đồ trong Core → hiện sơ đồ của hệ cũ (lưu một lần là chuyển sang Core).
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, authFetch, errorMessage, getJson, jsonOf, saveBlob } from "../../api-client";
import type { components } from "../../api-client/schema";
import type { Device } from "../../api-client/types";
import { realtime, useRealtime } from "../../realtime-client";
import { fmtTime } from "../../shared/metrics";
import { Modal } from "../../shared/ui";
import { MapCanvas } from "./MapCanvas";
import {
  autoLayout, blank, DECOR, DIR_NEXT, emptyMap, findHost, normalize, PC_H, PC_W, uid, type MapData, type MapResponse,
} from "./model";

type Props = {
  roomId: string;
  roomName: string;
  devices: Device[];
  devSel: Set<string>;
  onToggleDevice: (id: string) => void;
  onOpenDevice: (id: string) => void;
};

const MAX_HISTORY = 50;

export function RoomMap({ roomId, roomName, devices, devSel, onToggleDevice, onOpenDevice }: Props) {
  const qc = useQueryClient();
  const connected = useRealtime((s) => s.connected);
  const q = useQuery({
    queryKey: ["room-map", roomId],
    queryFn: () => getJson<MapResponse>(`/api/rooms/${encodeURIComponent(roomId)}/map`),
  });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<MapData | null>(null);
  const [past, setPast] = useState<MapData[]>([]);
  const [future, setFuture] = useState<MapData[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [zoom, setZoom] = useState(1);
  const [fitW, setFitW] = useState(1000);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "warn" | "err"; text: string } | null>(null);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [seat, setSeat] = useState("");
  const [gname, setGname] = useState("");
  const [wrapEl, setWrapEl] = useState<HTMLDivElement | null>(null);
  const fileIn = useRef<HTMLInputElement>(null);
  const editingRef = useRef(false);
  editingRef.current = editing;

  // Bề rộng khung → tỉ lệ "vừa khung". Theo dõi qua callback-ref: lần đầu component còn đang tải (chưa có khung)
  useEffect(() => {
    if (!wrapEl) return;
    const ro = new ResizeObserver(() => setFitW(wrapEl.clientWidth));
    ro.observe(wrapEl);
    setFitW(wrapEl.clientWidth);
    return () => ro.disconnect();
  }, [wrapEl]);

  // Người khác lưu sơ đồ phòng này → tải lại (đang sửa thì chỉ báo, không đè bản đang sửa)
  useEffect(() => {
    const s = realtime();
    if (!s || !connected) return;
    const on = (p: { room_id: string; by: string }) => {
      if (p.room_id !== roomId) return;
      if (editingRef.current) setNotice({ kind: "warn", text: `${p.by} vừa lưu sơ đồ phòng này — lưu bây giờ sẽ ghi đè bản đó.` });
      else void qc.invalidateQueries({ queryKey: ["room-map", roomId] });
    };
    s.on("room_map_updated", on);
    return () => {
      s.off("room_map_updated", on);
    };
  }, [roomId, connected, qc]);

  const saved = useMemo(() => (q.data?.map ? normalize(q.data.map) : null), [q.data]);
  const shown = editing ? draft : saved;
  const hosts = useMemo(() => devices.map((d) => d.hostname), [devices]);
  const devByHost = useMemo(() => new Map(devices.map((d) => [d.hostname.toUpperCase(), d])), [devices]);
  const unplaced = useMemo(() => {
    if (!shown) return [];
    const placed = new Set(shown.items.filter((i) => i.kind === "pc" || i.kind === "gv")
      .map((i) => findHost(i.seat, hosts)?.toUpperCase()).filter(Boolean));
    return devices.filter((d) => !placed.has(d.hostname.toUpperCase()));
  }, [shown, devices, hosts]);

  // tỉ lệ "vừa khung" tính theo nền + viền phòng (không theo phần tử) → kéo máy ra mép không làm nhảy tỉ lệ
  const baseW = shown ? Math.max(shown.canvas_w, shown.bounds.x + shown.bounds.w + 60) : 1000;
  const scale = Math.min(1.25, Math.max(0.2, (fitW - 4) / baseW)) * zoom; // tối đa 125%: thẻ máy không to quá
  const dirty = editing && past.length > 0;

  // ---------------------------------------------------------------- chỉnh sửa
  function begin(base: MapData) {
    setDraft(structuredClone(base));
    setPast([]);
    setFuture([]);
    setSel(new Set());
    setEditing(true);
    setNotice(null);
  }
  function stop() {
    setEditing(false);
    setDraft(null);
    setPast([]);
    setFuture([]);
    setSel(new Set());
    setConfirmLeave(false);
  }
  const commit = (before: MapData) => {
    setPast((p) => [...p.slice(-(MAX_HISTORY - 1)), before]);
    setFuture([]);
  };
  function change(next: MapData) {
    if (!draft) return;
    commit(draft);
    setDraft(next);
  }
  function undo() {
    if (!draft || !past.length) return;
    setFuture((f) => [draft, ...f]);
    setDraft(past[past.length - 1]);
    setPast((p) => p.slice(0, -1));
  }
  function redo() {
    if (!draft || !future.length) return;
    setPast((p) => [...p, draft]);
    setDraft(future[0]);
    setFuture((f) => f.slice(1));
  }
  const selected = () => draft?.items.filter((i) => sel.has(i.id)) ?? [];
  function add(kind: "pc" | "gv" | "board" | "ban-sv" | keyof typeof DECOR) {
    if (!draft) return;
    const at = { x: 150 + (draft.items.length % 8) * 12, y: 150 + (draft.items.length % 8) * 12 };
    let it;
    if (kind === "pc") {
      const s = seat.trim();
      if (!s) return setNotice({ kind: "warn", text: "Gõ số ghế (vd 49) rồi bấm Thêm máy." });
      const sv = /^\d$/.test(s) ? `0${s}` : s;
      if (draft.items.some((i) => i.kind === "pc" && i.seat === sv)) {
        return setNotice({ kind: "warn", text: `Đã có máy số ${sv} trên sơ đồ.` });
      }
      it = blank("pc", draft.items.some((i) => i.id === `pc-${sv}`) ? uid(`pc-${sv}`) : `pc-${sv}`,
        { seat: sv, ...at, w: PC_W, h: PC_H });
      setSeat("");
    } else if (kind === "gv") it = blank("gv", uid("item-desk"), { seat: "GV", ...at, w: 215, h: 108 });
    else if (kind === "board") it = blank("board", uid("item-bang"), { label: "BẢNG KÍNH", ...at, w: 400, h: 35 });
    else if (kind === "ban-sv") {
      const used = new Set(draft.items.filter((i) => i.kind === "ban-sv").map((i) => Number(i.label)));
      let n = 1;
      while (used.has(n)) n++;
      it = blank("ban-sv", uid("item-ban-sv"), { label: String(n).padStart(2, "0"), ...at, w: 105, h: 115 });
    } else {
      const dc = DECOR[kind];
      it = blank("decor", uid(`item-${kind}`), { decor: kind, ...at, w: dc.w, h: dc.h });
    }
    change({ ...draft, items: [...draft.items, it] });
    setSel(new Set([it.id]));
  }
  function removeSel() {
    if (!draft) return;
    const ids = new Set(selected().filter((i) => i.kind !== "door").map((i) => i.id));
    if (!ids.size) return;
    change({ ...draft, items: draft.items.filter((i) => !ids.has(i.id)) });
    setSel(new Set());
  }
  function rotate() {
    if (!draft) return;
    const ids = new Set(selected().filter((i) => i.kind === "pc" || i.kind === "gv").map((i) => i.id));
    if (!ids.size) return;
    const first = draft.items.find((i) => ids.has(i.id));
    const next = DIR_NEXT[first?.dir ?? ""];
    change({ ...draft, items: draft.items.map((i) => (ids.has(i.id) ? { ...i, dir: next } : i)) });
  }
  function group(make: boolean) {
    if (!draft) return;
    const ids = new Set(selected().filter((i) => i.kind === "pc").map((i) => i.id));
    if (!ids.size) return setNotice({ kind: "warn", text: "Chọn các máy cần gom cụm trước." });
    const shared = new Set(selected().map((i) => i.group).filter(Boolean));
    const gid = make ? (shared.size === 1 ? [...shared][0] as string : uid("g")) : null;
    const name = make ? (gname.trim() || "Cụm") : null;
    change({ ...draft, items: draft.items.map((i) => (ids.has(i.id) ? { ...i, group: gid, gname: name } : i)) });
    setGname("");
  }
  function nudge(dx: number, dy: number) {
    if (!draft || !sel.size) return;
    change({
      ...draft,
      items: draft.items.map((i) => {
        if (!sel.has(i.id)) return i;
        if (i.kind === "door") return { ...i, y: Math.max(0, Math.min(i.y + dy, draft.bounds.h - 80)) };
        return { ...i, x: i.x + dx, y: i.y + dy };
      }),
    });
  }
  function onKey(e: KeyboardEvent) {
    if (!editing || (e.target as HTMLElement).closest("input, select, textarea")) return;
    const step = e.shiftKey ? 10 : 1;
    const k = e.key;
    if (k === "ArrowLeft" || k === "ArrowRight" || k === "ArrowUp" || k === "ArrowDown") {
      e.preventDefault();
      nudge(k === "ArrowLeft" ? -step : k === "ArrowRight" ? step : 0, k === "ArrowUp" ? -step : k === "ArrowDown" ? step : 0);
    } else if (k === "Delete" || k === "Backspace") {
      e.preventDefault();
      removeSel();
    } else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    } else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "y") {
      e.preventDefault();
      redo();
    } else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "a") {
      e.preventDefault();
      setSel(new Set(draft?.items.map((i) => i.id)));
    } else if (k === "Escape") setSel(new Set());
  }

  // ---------------------------------------------------------------- lưu / Excel
  async function save() {
    if (!draft) return;
    setBusy(true);
    const res = await api().PUT("/api/rooms/{room_id}/map", {
      params: { path: { room_id: roomId } }, body: draft as components["schemas"]["MapModel"],
    });
    setBusy(false);
    if (!res.response.ok) return setNotice({ kind: "err", text: errorMessage(res.error) });
    const r = res.data as unknown as { export_error: string | null; exported: string | null };
    stop();
    void qc.invalidateQueries({ queryKey: ["room-map", roomId] });
    setNotice(r.export_error
      ? { kind: "warn", text: `Đã lưu sơ đồ, nhưng CHƯA xuất được tệp cho hệ thi: ${r.export_error}` }
      : { kind: "ok", text: `Đã lưu sơ đồ (đã xuất ${r.exported} cho hệ thi).` });
  }
  async function importExcel(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f || !draft) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("map", JSON.stringify(draft));
    setBusy(true);
    try {
      const r = await jsonOf<{ map: MapData; kind: "grid" | "codes"; count: number }>(
        await authFetch(`/api/rooms/${encodeURIComponent(roomId)}/map/import-excel`, { method: "POST", body: fd }));
      change(normalize(r.map));
      setSel(new Set());
      setNotice({ kind: "ok", text: r.kind === "grid" ? `Đã dựng ${r.count} máy từ ${f.name} — kiểm tra rồi bấm Lưu.`
        : `Đã cập nhật mã thiết bị cho ${r.count} phần tử từ ${f.name} — bấm Lưu để giữ.` });
    } catch (err) {
      setNotice({ kind: "err", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }
  async function exportExcel() {
    const m = shown;
    if (!m) return;
    setBusy(true);
    try {
      const res = await authFetch(`/api/rooms/${encodeURIComponent(roomId)}/map/export-excel`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(m),
      });
      if (!res.ok) await jsonOf(res);
      saveBlob(await res.blob(), `So_Do_${roomName.replace(/\s+/g, "_")}.xlsx`);
    } catch (err) {
      setNotice({ kind: "err", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  if (q.isPending) return <p className="muted">Đang tải sơ đồ…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;
  const canEdit = q.data.can_edit;

  return (
    <div className="room-map">
      <div className="map-toolbar">
        {!editing ? (
          <>
            {canEdit && shown && <button onClick={() => begin(shown)}>Sửa sơ đồ</button>}
            {shown && <button className="ghost" onClick={() => void exportExcel()} disabled={busy}>Xuất Excel</button>}
            <span className="muted small">
              {q.data.source === "legacy" ? "Đang hiển thị sơ đồ của hệ cũ — lưu một lần để đưa vào Core."
                : q.data.source === "core" ? `Lưu lúc ${fmtTime(q.data.updated_at)} bởi ${q.data.updated_by ?? "?"}` : ""}
            </span>
          </>
        ) : (
          <>
            <input className="seat-in" value={seat} onChange={(e) => setSeat(e.target.value.slice(0, 16))}
                   placeholder="Số ghế" aria-label="Số ghế máy mới" onKeyDown={(e) => e.key === "Enter" && add("pc")} />
            <button className="ghost small" onClick={() => add("pc")}>+ Máy</button>
            <select className="add-sel" value="" aria-label="Thêm phần tử khác"
                    onChange={(e) => e.target.value && add(e.target.value as Parameters<typeof add>[0])}>
              <option value="">+ Thêm…</option>
              <option value="gv">Bàn giáo viên</option>
              <option value="board">Bảng kính</option>
              <option value="ban-sv">Bàn sinh viên</option>
              {Object.entries(DECOR).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
            <span className="sep" />
            <button className="ghost small" onClick={rotate} disabled={!sel.size} title="Đổi hướng máy đang chọn">Xoay hướng</button>
            <input className="seat-in" value={gname} onChange={(e) => setGname(e.target.value.slice(0, 60))}
                   placeholder="Tên cụm" aria-label="Tên cụm máy" />
            <button className="ghost small" onClick={() => group(true)} disabled={!sel.size}>Gom cụm</button>
            <button className="ghost small" onClick={() => group(false)} disabled={!sel.size}>Bỏ cụm</button>
            <button className="ghost small danger-text" onClick={removeSel} disabled={!sel.size}>Xoá</button>
            <span className="sep" />
            <button className="ghost small" onClick={undo} disabled={!past.length} title="Ctrl+Z">↶</button>
            <button className="ghost small" onClick={redo} disabled={!future.length} title="Ctrl+Y">↷</button>
            <button className="ghost small" onClick={() => fileIn.current?.click()} disabled={busy}>Nhập Excel</button>
            <button className="ghost small" onClick={() => void exportExcel()} disabled={busy}>Xuất Excel</button>
            <input ref={fileIn} type="file" accept=".xlsx" hidden onChange={(e) => void importExcel(e)} />
            <span className="sep" />
            <button onClick={() => void save()} disabled={busy}>{busy ? "Đang lưu…" : "Lưu"}</button>
            <button className="ghost" onClick={() => (dirty ? setConfirmLeave(true) : stop())} disabled={busy}>Huỷ</button>
          </>
        )}
        <span className="zoom">
          <button className="ghost small" onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.1).toFixed(2)))}>−</button>
          <button className="ghost small" onClick={() => setZoom(1)} title="Vừa khung">{Math.round(zoom * 100)}%</button>
          <button className="ghost small" onClick={() => setZoom((z) => Math.min(3, +(z + 0.1).toFixed(2)))}>+</button>
        </span>
      </div>
      {editing && (
        <p className="muted small hint">
          Kéo để di chuyển (hít lưới — giữ Alt để đặt tự do) · khoanh vùng hoặc Ctrl+bấm để chọn nhiều · mũi tên dịch
          1px (Shift 10px) · Delete xoá · Ctrl+Z / Ctrl+Y · cửa chỉ trượt dọc theo tường.
        </p>
      )}
      {notice && <p className={notice.kind === "ok" ? "notice" : notice.kind === "warn" ? "warn-box" : "error"}>{notice.text}</p>}
      <div className="map-wrap" ref={setWrapEl} tabIndex={0} onKeyDown={onKey}
           onWheel={(e) => {
             if (!e.ctrlKey) return;
             e.preventDefault();
             setZoom((z) => Math.min(3, Math.max(0.4, +(z + (e.deltaY < 0 ? 0.1 : -0.1)).toFixed(2))));
           }}>
        {shown ? (
          <MapCanvas map={shown} roomName={roomName} editing={editing} scale={scale} hosts={hosts} devByHost={devByHost}
                     sel={sel} devSel={devSel} onSel={setSel} onLive={setDraft} onCommit={commit}
                     onOpenDevice={onOpenDevice} onToggleDevice={onToggleDevice} />
        ) : (
          <div className="map-empty">
            <p>Phòng chưa có sơ đồ.</p>
            {canEdit && (
              <p>
                <button onClick={() => begin(autoLayout(hosts))} disabled={!hosts.length}>Tạo từ danh sách máy</button>{" "}
                <button className="ghost" onClick={() => begin(emptyMap())}>Sơ đồ trống</button>
              </p>
            )}
          </div>
        )}
      </div>
      {!editing && shown && unplaced.length > 0 && (
        <p className="muted small">Máy chưa có trên sơ đồ ({unplaced.length}): {unplaced.map((d) => d.hostname).join(", ")}</p>
      )}
      {confirmLeave && (
        <Modal title="Bỏ các thay đổi chưa lưu?" onClose={() => setConfirmLeave(false)}>
          <p>Sơ đồ đang sửa có {past.length} thao tác chưa lưu.</p>
          <div className="actions">
            <button className="ghost" onClick={() => setConfirmLeave(false)} autoFocus>Sửa tiếp</button>
            <button className="danger" onClick={stop}>Bỏ thay đổi</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
