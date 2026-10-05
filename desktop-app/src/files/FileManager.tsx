// Trình quản lý tệp 2 khung (Sổ tay 7.2) — kiểu "Browse Files" của AnyDesk, mang từ fbrowser.js hệ cũ.
// Khung trái tự nhận CHÍNH máy đang mở Desktop (Core dò ngược IP, máy phải đang chạy agent); khung phải để trống (hoặc máy
// được mở từ trang máy). "Máy chủ" = kho riêng của tổ chức, chỉ Super Admin. Luôn chỉ MỘT cửa sổ (trang gọi tự lo).
// Phím tắt như Explorer: Ctrl+A/X/C/V/Z/Y/P · F2 · F5 · Delete (Thùng rác) · Shift+Delete (xoá hẳn) · Backspace (lên) ·
// Tab (sang khung kia) · gõ chữ để nhảy tới mục · Esc (bỏ cắt/sao chép).
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type MouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { Device, ListResult } from "../api-client/types";
import { FilePane } from "./FilePane";
import { FsWindow, human, type FsPane, type Info, type Props } from "./pane";

export function FileManager({ roomId, deviceId, onClose }: { roomId: string; deviceId?: string; onClose: () => void }) {
  const win = useMemo(() => new FsWindow(), []);
  useSyncExternalStore(win.subscribe, win.snap);
  const [ctx, setCtx] = useState<{ x: number; y: number; pane: FsPane } | null>(null);
  const devQ = useQuery({
    queryKey: ["fm-devices", roomId],
    queryFn: () => getJson<ListResult<Device>>(`/api/devices?room_id=${encodeURIComponent(roomId)}`),
    refetchInterval: 15000, // máy mới online thì hiện, máy offline thì rút (máy đang mở vẫn giữ)
  });
  const who = useQuery({ queryKey: ["fm-whoami"], queryFn: () => getJson<Info>("/api/files/whoami") });
  const inited = useRef(false);

  useEffect(() => {
    if (devQ.data) win.setMachines(devQ.data.items.map((d) => ({ id: d.id, hostname: d.hostname, is_online: d.is_online })));
  }, [devQ.data, win]);

  useEffect(() => { // chọn nguồn mặc định MỘT lần, khi đã biết danh sách máy + "tôi là ai"
    if (inited.current || !devQ.data || !who.data) return;
    inited.current = true;
    win.info = who.data;
    const self = who.data.self_device?.id ?? "";
    const has = (id: string) => win.machines.some((m) => m.id === id);
    if (self && has(self)) win.choose(win.panes[0], self);
    else win.panes[0].clear();
    if (deviceId && deviceId !== self && has(deviceId)) win.choose(win.panes[1], deviceId);
    else win.panes[1].clear();
  }, [devQ.data, who.data, deviceId, win]);

  // Phím tắt — chỉ cho khung đang focus, không bắt phím khi đang gõ trong ô nhập
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const p = win.focused;
      const tag = (e.target as HTMLElement | null)?.tagName ?? "";
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      const key = e.key.toLowerCase();
      const c = e.ctrlKey || e.metaKey;
      const act = (fn: () => unknown) => {
        e.preventDefault();
        void fn();
      };
      if (e.key === "Escape") {
        if (win.propsData) return win.showProps(null);
        setCtx(null);
        p.clip = null;
        p.resetTyping();
        return p.emit();
      }
      if (win.propsData) return;
      if (c && key === "a") act(() => p.selectAll());
      else if (c && key === "x") act(() => p.mark("cut"));
      else if (c && key === "c") act(() => p.mark("copy"));
      else if (c && key === "v") act(() => p.paste());
      else if (c && key === "z") act(() => p.undoAct());
      else if (c && key === "y") act(() => p.undoAct(true));
      else if (c && key === "p") act(() => p.props());
      else if (e.key === "F2") act(() => p.startRename());
      else if (e.key === "F5") act(() => p.go(p.path, true));
      else if (e.key === "Delete") act(() => p.del(e.shiftKey));
      else if (e.key === "Backspace") act(() => p.up());
      else if (e.key === "Tab") act(() => win.focus(p.other()));
      else if (e.key === "Enter" && p.sel.size === 1) act(() => p.open([...p.sel][0]));
      else if (!c && !e.altKey && e.key.length === 1 && e.key !== " ") act(() => p.typeAhead(e.key));
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [win]);

  useEffect(() => { // bấm ra ngoài / cuộn → đóng menu phải
    if (!ctx) return;
    const off = () => setCtx(null);
    window.addEventListener("click", off);
    window.addEventListener("scroll", off, true);
    return () => {
      window.removeEventListener("click", off);
      window.removeEventListener("scroll", off, true);
    };
  }, [ctx]);

  const p = win.focused;
  const onCtx = (e: MouseEvent, pane: FsPane) => setCtx({ x: e.clientX, y: e.clientY, pane });

  return (
    <div className="fm-back" role="dialog" aria-label="Trình quản lý tệp">
      <div className="fm-win">
        <div className="fm-hd">
          <b>📂 {win.title()}</b>
          <button className="ghost" onClick={onClose} title="Đóng">✕</button>
        </div>
        {(devQ.isError || who.isError) && (
          <p className="error fm-err">{(devQ.error ?? who.error)?.message}</p>
        )}
        <div className="fm-bd">
          <FilePane pane={win.panes[0]} win={win} onCtx={onCtx} />
          <FilePane pane={win.panes[1]} win={win} onCtx={onCtx} />
        </div>
        <div className="fm-tb">
          <button onClick={() => void p.toMyPC()}>⬇ Về máy tôi</button>
          <button onClick={() => p.pickUpload?.()} disabled={!p.src}>⬆ Từ máy tôi</button>
          <button onClick={() => void p.mkdir()} disabled={!p.src}>📁+ Thư mục mới</button>
          <button onClick={() => p.startRename()}>✏ Đổi tên</button>
          <button onClick={() => void p.sendTo(p.other())} title="Chép mục đã chọn sang thư mục đang mở ở khung kia">
            ⇄ Chép sang khung kia
          </button>
          <button className="danger-soft" onClick={() => void p.del(false)}>🗑 Thùng rác</button>
          <span className="grow" />
          <button onClick={() => void p.go(p.path, true)} disabled={!p.src}>⟳ Làm mới</button>
        </div>
        {win.rows.length > 0 && (
          <div className="fm-q" aria-label="Hàng đợi truyền tệp">
            {win.rows.map((r) => (
              <div key={r.id} className={`fm-qr ${r.state}`}>
                <div className="t"><b>{r.name}</b><i>{r.route} · {r.label}</i></div>
                <div className="bar"><i style={{ width: `${r.pct}%` }} /></div>
              </div>
            ))}
          </div>
        )}
      </div>
      {ctx && <CtxMenu ctx={ctx} onPick={() => setCtx(null)} />}
      {win.propsData && <PropsDialog p={win.propsData} onClose={() => win.showProps(null)} />}
    </div>
  );
}

function CtxMenu({ ctx, onPick }: { ctx: { x: number; y: number; pane: FsPane }; onPick: () => void }) {
  const p = ctx.pane;
  const n = p.sel.size;
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: ctx.x, y: ctx.y });
  useEffect(() => { // không tràn ra ngoài cửa sổ
    const m = ref.current;
    if (!m) return;
    setPos({ x: Math.min(ctx.x, window.innerWidth - m.offsetWidth - 4),
      y: Math.min(ctx.y, window.innerHeight - m.offsetHeight - 4) });
  }, [ctx]);
  const item = (label: string, fn: () => unknown, cls = "") => (
    <div className={`i ${cls}`} onClick={() => {
      onPick();
      void fn();
    }}>{label}</div>
  );
  return (
    <div ref={ref} className="fm-ctx" style={{ left: pos.x, top: pos.y }} onClick={(e) => e.stopPropagation()}>
      {n > 0 && item("⬇️ Tải về máy tôi", () => p.toMyPC())}
      {n > 0 && item("⇄ Chép sang khung kia", () => p.sendTo(p.other()))}
      {n > 0 && <div className="sep" />}
      {n > 0 && item("✂️ Cắt (Ctrl+X)", () => p.mark("cut"))}
      {n > 0 && item("📑 Sao chép (Ctrl+C)", () => p.mark("copy"))}
      {!!p.clip?.items.length && item("📋 Dán vào đây (Ctrl+V)", () => p.paste())}
      {n === 1 && item("✏️ Đổi tên (F2)", () => p.startRename())}
      {n > 0 && item("🗑️ Vào Thùng rác (Delete)", () => p.del(false), "d")}
      {n > 0 && item("❌ Xoá vĩnh viễn (Shift+Delete)", () => p.del(true), "d")}
      <div className="sep" />
      {item("📁 Tạo thư mục", () => p.mkdir())}
      {item("⬆️ Tải lên đây", () => p.pickUpload?.())}
      {n === 1 && item("ℹ️ Thuộc tính (Ctrl+P)", () => p.props())}
    </div>
  );
}

function PropsDialog({ p, onClose }: { p: Props; onClose: () => void }) {
  const isDir = p.type === "dir";
  const date = (s?: number) => (s ? new Date(s * 1000).toLocaleString("vi-VN", {
    weekday: "long", year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit",
    second: "2-digit" }) : "—");
  const bytes = (n?: number) => `${human(Number(n || 0))} (${Number(n || 0).toLocaleString("vi-VN")} bytes)`;
  const rows: [string, string][] = [
    ["Loại", isDir ? "Thư mục" : p.ext ? `Tệp ${p.ext.replace(/^\./, "").toUpperCase()}` : "Tệp"],
    ["Vị trí", p.location || "—"],
    ["Kích thước", bytes(p.size)],
    ["Trên đĩa", bytes(p.disk || p.size)],
  ];
  if (isDir && (p.files != null || p.folders != null)) {
    rows.push(["Gồm", `${(p.files ?? 0).toLocaleString("vi-VN")} tệp, ${(p.folders ?? 0).toLocaleString("vi-VN")} thư mục`]);
  }
  if (p.created) rows.push(["Tạo lúc", date(p.created)]);
  rows.push(["Sửa lúc", date(p.modified)]);
  if (p.accessed) rows.push(["Mở lúc", date(p.accessed)]);
  if (p.attrs) rows.push(["Thuộc tính", p.attrs]);
  rows.push(["Nguồn", p.src]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={`Thuộc tính ${p.name}`}>
        <h2>{isDir ? "📁" : "📄"} {p.name}</h2>
        <dl className="kv">
          {rows.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
        <div className="actions"><button onClick={onClose}>OK</button></div>
      </div>
    </div>
  );
}
