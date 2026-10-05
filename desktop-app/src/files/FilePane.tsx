// Một khung của trình quản lý tệp — vẽ trạng thái của FsPane (pane.ts). Kéo-thả giống Explorer (bê từ fbrowser.js):
//  - kéo trong CHÍNH khung này lên một THƯ MỤC khác = DI CHUYỂN vào đó (thả ra chỗ trống: không làm gì);
//  - kéo từ khung kia = CHÉP sang; trỏ đúng một thư mục → chép VÀO thư mục đó (sáng riêng dòng), chỗ trống → thư mục
//    đang mở (sáng cả khung);
//  - kéo tệp từ Explorer của máy bạn = TẢI LÊN (cần `dragDropEnabled: false` ở cửa sổ Tauri, nếu không WebView2 nuốt mất).
// Icon chỉ dùng ký tự Unicode + huy hiệu màu theo đuôi tệp (như hệ cũ — không phụ thuộc thư viện icon).
import { useLayoutEffect, useRef, useState, useSyncExternalStore, type DragEvent, type MouseEvent } from "react";
import { SRV, type FsItem } from "./transport";
import { human, type FsPane, type FsWindow, type SortKey } from "./pane";

const ICO: Record<string, string> = {
  doc: "#2b579a", docx: "#2b579a", rtf: "#2b579a", odt: "#2b579a",
  xls: "#217346", xlsx: "#217346", xlsm: "#217346", csv: "#217346", ods: "#217346",
  ppt: "#d24726", pptx: "#d24726", pdf: "#d93831",
  zip: "#c98a10", rar: "#c98a10", "7z": "#c98a10", tar: "#c98a10", gz: "#c98a10", iso: "#7c3aed",
  jpg: "#8b5cf6", jpeg: "#8b5cf6", png: "#8b5cf6", gif: "#8b5cf6", bmp: "#8b5cf6", webp: "#8b5cf6", ico: "#8b5cf6",
  svg: "#8b5cf6", mp3: "#db2777", wav: "#db2777", wma: "#db2777", m4a: "#db2777", flac: "#db2777", aac: "#db2777",
  ogg: "#db2777", mp4: "#0284c7", avi: "#0284c7", mkv: "#0284c7", mov: "#0284c7", wmv: "#0284c7", flv: "#0284c7",
  exe: "#475569", msi: "#475569", bat: "#475569", cmd: "#475569", ps1: "#0369a1", vbs: "#475569",
  lnk: "#94a3b8", url: "#94a3b8", txt: "#64748b", log: "#64748b", ini: "#64748b", cfg: "#64748b", md: "#64748b",
  py: "#3776ab", js: "#ca8a04", html: "#e34c26", css: "#264de4", json: "#6b7280", xml: "#6b7280", sql: "#0f766e",
  db: "#4b5563", sqlite: "#4b5563", bak: "#4b5563",
};

function Icon({ it }: { it: FsItem }) {
  if (it.type === "dir") return <span className="fm-ic dir">📁</span>;
  const ext = (/\.([A-Za-z0-9]{1,5})$/.exec(it.name)?.[1] ?? "").toLowerCase();
  return <span className="fm-ic" style={{ background: ICO[ext] ?? "#9aa5b1" }}>{(ext || "?").slice(0, 3).toUpperCase()}</span>;
}

function when(t: number): string {
  if (!t) return "";
  const d = new Date(t * 1000);
  const p = (x: number) => String(x).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function FilePane({ pane, win, onCtx }: {
  pane: FsPane; win: FsWindow; onCtx: (e: MouseEvent, p: FsPane) => void;
}) {
  useSyncExternalStore(pane.subscribe, pane.snap);
  useSyncExternalStore(win.subscribe, win.snap);
  const listRef = useRef<HTMLDivElement>(null);
  const upRef = useRef<HTMLInputElement>(null);
  // Đang mở ô chọn nguồn → GIỮ danh sách cũ (máy vừa offline không biến mất ngay dưới con trỏ — bài học fbrowser)
  const [srcOpen, setSrcOpen] = useState(false);
  const held = useRef(win.options(pane));
  if (!srcOpen) held.current = win.options(pane);
  const opts = held.current;

  useLayoutEffect(() => {
    pane.listEl = listRef.current;
    pane.pickUpload = () => upRef.current?.click();
  }, [pane]);

  // Sau khi vẽ lại danh sách: đặt chỗ cuộn rồi đưa mục vừa thao tác vào tầm nhìn — CHỈ cuộn trong khung list
  useLayoutEffect(() => {
    const L = listRef.current;
    if (!L) return;
    L.scrollTop = pane.view.top;
    if (pane.view.row < 0) return;
    const r = L.querySelector<HTMLElement>(`[data-i="${pane.view.row}"]`);
    if (!r) return;
    if (r.offsetTop < L.scrollTop) L.scrollTop = r.offsetTop;
    else if (r.offsetTop + r.offsetHeight > L.scrollTop + L.clientHeight) {
      L.scrollTop = r.offsetTop + r.offsetHeight - L.clientHeight;
    }
  }, [pane, pane.view.seq]);

  const rowOf = (t: EventTarget | null): number => {
    const el = (t as HTMLElement | null)?.closest?.<HTMLElement>("[data-i]");
    return el ? Number(el.dataset.i) : -1;
  };

  const clearDrop = () => {
    if (pane.dropRow !== -1 || pane.dropPane) {
      pane.dropRow = -1;
      pane.dropPane = false;
      pane.emit();
    }
  };

  const onDragOver = (e: DragEvent) => {
    const isOs = Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const from = win.drag?.from;
    if (!(isOs || from)) return;
    const i = rowOf(e.target);
    const it = i >= 0 ? pane.items[i] : undefined;
    if (from === pane) { // trong cùng khung: chỉ thả được lên một THƯ MỤC khác
      if (!it || it.type !== "dir" || pane.sel.has(i)) return clearDrop();
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      if (pane.dropRow !== i || pane.dropPane) {
        pane.dropRow = i;
        pane.dropPane = false;
        pane.status = { msg: `⇢ Chuyển vào thư mục "${it.name}"`, err: false };
        pane.emit();
      }
      return;
    }
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    const row = it?.type === "dir" ? i : -1;
    if (pane.dropRow !== row || pane.dropPane !== (row < 0)) {
      pane.dropRow = row;
      pane.dropPane = row < 0;
      if (it?.type === "dir") pane.status = { msg: `⇢ Chép vào thư mục "${it.name}"`, err: false };
      pane.emit();
    }
  };

  const onDrop = (e: DragEvent) => {
    const intoName = pane.dropRow >= 0 ? pane.items[pane.dropRow]?.name ?? "" : "";
    const into = intoName ? pane.full(intoName) : "";
    clearDrop();
    const d = win.drag;
    win.drag = null;
    if (d?.from === pane) {
      e.preventDefault();
      if (intoName) void pane.moveInto(d.items, intoName);
    } else if (d) {
      e.preventDefault();
      void d.from.sendTo(pane, d.items, into);
    } else if (e.dataTransfer?.files?.length) {
      e.preventDefault();
      void pane.uploadFromPC(Array.from(e.dataTransfer.files), into);
    }
  };

  const isFocused = win.focused === pane;
  const pathShown = pane.path || (pane.src === SRV ? "\\ (Kho máy chủ)" : pane.src ? "\\ (Ổ đĩa)" : "");
  const sortMark = (k: SortKey) => (pane.sort === k ? (pane.desc ? " ▼" : " ▲") : "");

  return (
    <div className={`fm-pane${isFocused ? " on" : ""}`} onMouseDownCapture={() => win.focus(pane)}>
      <div className="fm-src">
        <span aria-hidden>🖧</span>
        <select value={pane.src} aria-label={`Nguồn khung ${pane.side === "L" ? "trái" : "phải"}`}
                onMouseDown={() => setSrcOpen(true)} onFocus={() => setSrcOpen(true)} onBlur={() => setSrcOpen(false)}
                onChange={(e) => {
                  setSrcOpen(false);
                  win.choose(pane, e.target.value);
                }}>
          {opts.map((o) => <option key={o.value || "none"} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      <div className="fm-nav">
        <button title="Quay lại" onClick={() => pane.back()} disabled={!pane.hist.length}>←</button>
        <button title="Lên thư mục cha (Backspace)" onClick={() => pane.up()} disabled={!pane.path}>↑</button>
        <button title={pane.src === SRV ? "Về gốc kho" : "Về danh sách ổ đĩa"} onClick={() => void pane.go("")}
                disabled={!pane.src}>🖴</button>
        <button title="Tải lại (F5)" onClick={() => void pane.go(pane.path, true)} disabled={!pane.src}>⟳</button>
        <input key={`${pane.src}|${pane.path}`} defaultValue={pathShown} placeholder="Đường dẫn..." aria-label="Đường dẫn"
               onFocus={(e) => {
                 if (!pane.path) e.currentTarget.value = "";
               }}
               onKeyDown={(e) => {
                 if (e.key === "Enter") void pane.go(e.currentTarget.value.trim());
                 if (e.key === "Escape") e.currentTarget.value = pathShown;
               }} />
      </div>
      <div className="fm-col">
        {(["name", "size", "mtime"] as SortKey[]).map((k) => (
          <span key={k} onClick={() => pane.setSort(k)}>
            {{ name: "Tên", size: "Kích thước", mtime: "Sửa đổi" }[k]}{sortMark(k)}
          </span>
        ))}
      </div>
      <div ref={listRef} className={`fm-list${pane.dropPane ? " drop" : ""}`} tabIndex={-1}
           onMouseDown={(e) => {
             if (e.detail > 1) e.preventDefault(); // bấm đúp không bôi đen chữ
           }}
           onClick={(e) => {
             const i = rowOf(e.target);
             if (i >= 0) pane.click(i, e.shiftKey, e.ctrlKey || e.metaKey);
           }}
           onDoubleClick={(e) => {
             const i = rowOf(e.target);
             if (i >= 0) pane.open(i);
           }}
           onContextMenu={(e) => {
             e.preventDefault();
             win.focus(pane);
             const i = rowOf(e.target);
             if (i >= 0) pane.ensureSelected(i);
             onCtx(e, pane);
           }}
           onDragStart={(e) => {
             const i = rowOf(e.target);
             if (i < 0) return e.preventDefault();
             pane.ensureSelected(i); // kéo mục chưa chọn → chọn nó
             win.drag = { from: pane, items: pane.selItems() };
             e.dataTransfer.setData("text/plain", pane.selItems().map((x) => x.name).join("\n"));
             e.dataTransfer.effectAllowed = "copyMove";
           }}
           onDragEnd={() => {
             win.drag = null;
             clearDrop();
           }}
           onDragEnter={onDragOver} onDragOver={onDragOver}
           onDragLeave={(e) => {
             if (!listRef.current?.contains(e.relatedTarget as Node | null)) clearDrop();
           }}
           onDrop={onDrop}>
        {!pane.src ? (
          <div className="fm-empty">Chọn máy ở ô trên để bắt đầu.</div>
        ) : (
          <>
            {pane.path && (
              <div className="fm-row up" onClick={(e) => {
                e.stopPropagation();
                pane.up();
              }}>
                <span className="n"><span className="fm-ic up">↰</span><b>..</b></span><span /><span />
              </div>
            )}
            {pane.items.map((it, i) => (
              <div key={it.name} data-i={i} draggable={pane.renaming !== i}
                   className={`fm-row${pane.sel.has(i) ? " sel" : ""}${pane.isCut(it.name) ? " cut" : ""}` +
                     `${pane.dropRow === i ? " dropinto" : ""}${it.type === "dir" ? " dir" : ""}`}>
                <span className="n">
                  <Icon it={it} />
                  {pane.renaming === i ? <RenameBox pane={pane} it={it} /> : <b title={it.name}>{it.name}</b>}
                </span>
                <span className="s">{it.type === "dir" ? "" : human(it.size)}</span>
                <span className="m">{when(it.mtime)}</span>
              </div>
            ))}
            {pane.items.length === 0 && pane.status.msg !== "⏳ Đang tải..." && (
              <div className="fm-empty">Thư mục trống.</div>
            )}
          </>
        )}
      </div>
      <div className={`fm-st${pane.status.err ? " err" : ""}`} title={pane.status.msg}>{pane.status.msg}</div>
      <input ref={upRef} type="file" multiple hidden onChange={(e) => {
        const fs = Array.from(e.currentTarget.files ?? []);
        e.currentTarget.value = "";
        if (fs.length) void pane.uploadFromPC(fs);
      }} />
    </div>
  );
}

/** Đổi tên ngay tại dòng (như Explorer): bôi sẵn phần tên (chừa đuôi), Enter = xác nhận, Esc = huỷ, bấm ra ngoài = xác nhận. */
function RenameBox({ pane, it }: { pane: FsPane; it: FsItem }) {
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    const dot = it.type === "dir" ? -1 : it.name.lastIndexOf(".");
    el.setSelectionRange(0, dot > 0 ? dot : it.name.length);
  }, [it]);
  const finish = (commit: boolean) => {
    if (done.current) return;
    done.current = true;
    void pane.finishRename(commit, ref.current?.value ?? "");
  };
  return (
    <input ref={ref} className="fm-ren" defaultValue={it.name} aria-label="Tên mới"
           onKeyDown={(e) => {
             e.stopPropagation(); // phím tắt cửa sổ (F2/Delete/gõ-nhảy) không bắt phím của ô sửa tên
             if (e.key === "Enter") {
               e.preventDefault();
               finish(true);
             } else if (e.key === "Escape") {
               e.preventDefault();
               finish(false);
             }
           }}
           onBlur={() => finish(true)} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}
           onMouseDown={(e) => e.stopPropagation()} />
  );
}
