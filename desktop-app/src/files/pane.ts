// Logic MỘT khung + cửa sổ 2 khung — chuyển gần 1:1 từ FbPane / FbWindow của D:\NetworkInventory\fbrowser.js (v13),
// giữ nguyên các hành vi đã tinh chỉnh nhiều tháng (đừng "làm gọn" mà mất):
//  - Mọi thao tác thay đổi dữ liệu tải lại TẠI CHỖ: giữ chỗ cuộn + chọn đúng mục vừa thao tác (kiểu Explorer); xoá xong
//    chọn dòng kế ở đúng vị trí; chỉ điều hướng thường mới về đầu danh sách.
//  - Back về ĐÚNG chỗ cuộn lúc rời đi và chọn sẵn thư mục vừa thoát ra: lịch sử lưu {p, top, name}, đẩy TRƯỚC khi tải
//    (sau đó scrollTop đã về 0); `name` chỉ đặt khi bước vào thư mục con TRỰC TIẾP.
//  - Hai khung không bao giờ cùng nguồn: chọn trùng → HOÁN ĐỔI (khung kia nhận nguồn cũ của khung vừa đổi).
//  - Thư mục tự nén .zip ở đầu gửi, tự giải nén ở đầu nhận; tiến độ theo fs_progress (trạm → trạm 2 chặng, mỗi chặng 50%).
// Lớp thuần (không phải hook) + subscribe → React vẽ lại; tránh closure cũ khi các thao tác bất đồng bộ chồng nhau.
import { authFetch } from "../api-client";
import { fsSend, LONG, newToken, pickSink, pulledPath, putFile, SRV, srvFilePath, srvUpload, type FsItem,
         type FsRes, type Progress } from "./transport";

export type Machine = { id: string; hostname: string; is_online: boolean; kept?: boolean };
export type Info = { super: boolean; self_device: { id: string; hostname: string } | null };
type Hist = { p: string; top: number; name: string };
type Move = { src: string; dst: string };
type GoOpts = { keepScroll?: boolean; selectNames?: string[]; selectIndex?: number; scrollTop?: number };
export type SortKey = "name" | "size" | "mtime";
export type QRow = { id: number; name: string; route: string; pct: number; label: string; state: "run" | "ok" | "err" };
export type Props = { name: string; type: string; location?: string; size?: number; disk?: number; files?: number;
  folders?: number; created?: number; modified?: number; accessed?: number; attrs?: string; ext?: string; src: string };

export const join = (dir: string, name: string) => (dir ? dir.replace(/[\\/]+$/, "") + "\\" : "") + name;
const base = (p: string) => String(p || "").split(/[\\/]/).pop() ?? "";
const BAD_NAME = /[\\/:*?"<>|]/;

export function human(n: number): string {
  if (!n) return "0 B";
  if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB";
  if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " KB";
  return n + " B";
}

function copyName(n: string, isDir: boolean): string {
  if (isDir) return n + " - Copy";
  const d = n.lastIndexOf(".");
  return d > 0 ? n.slice(0, d) + " - Copy" + n.slice(d) : n + " - Copy";
}

/** Chạy lần lượt tối đa `n` việc cùng lúc (xoá nhiều mục…) — đủ nhanh mà không dội máy trạm. */
async function pool<T, R>(items: T[], n: number, fn: (x: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (i < items.length) {
      const k = i++;
      out[k] = await fn(items[k]);
    }
  }));
  return out;
}

class Store {
  private v = 0;
  private subs = new Set<() => void>();
  subscribe = (cb: () => void) => {
    this.subs.add(cb);
    return () => {
      this.subs.delete(cb);
    };
  };
  snap = () => this.v;
  emit() {
    this.v++;
    this.subs.forEach((f) => f());
  }
}

// ====================================================================== KHUNG
export class FsPane extends Store {
  src = "";
  prevSrc = "";
  path = "";
  items: FsItem[] = [];
  sel = new Set<number>();
  anchor = -1;
  hist: Hist[] = [];
  sort: SortKey = "name";
  desc = false;
  clip: { mode: "cut" | "copy"; items: { name: string; type: string }[]; dir: string; src: string } | null = null;
  undo: { list: Move[] }[] = [];
  redo: { list: Move[] }[] = [];
  status = { msg: "Chọn nguồn để bắt đầu.", err: false };
  renaming: number | null = null;
  view: { seq: number; top: number; row: number } = { seq: 0, top: 0, row: -1 };
  dropRow = -1; // dòng thư mục đang được trỏ khi kéo-thả (sáng riêng dòng đó)
  dropPane = false; // kéo vào chỗ trống → sáng cả khung
  listEl: HTMLDivElement | null = null;
  pickUpload: (() => void) | null = null;
  private tBuf = "";
  private tIdx = -1;
  private tLast = 0;
  private reqSeq = 0;

  constructor(public win: FsWindow, public side: "L" | "R") {
    super();
  }

  isSrv() {
    return this.src === SRV;
  }
  label() {
    return this.isSrv() ? "Máy chủ" : this.win.hostName(this.src) || "Chưa chọn";
  }
  full(name: string) {
    return join(this.path, name);
  }
  other(): FsPane {
    return this.win.panes[this.side === "L" ? 1 : 0];
  }
  selItems(): FsItem[] {
    return [...this.sel].map((i) => this.items[i]).filter(Boolean);
  }
  st(msg: string, err = false) {
    this.status = { msg, err };
    this.emit();
  }
  summary() {
    return `${this.label()} · ${this.items.length} mục · ${this.path || (this.isSrv() ? "Kho máy chủ" : "Ổ đĩa")}` +
      (this.sel.size ? ` · đã chọn ${this.sel.size}` : "");
  }
  /** Ở gốc máy trạm (danh sách ổ đĩa) không tạo/tải lên được; gốc kho máy chủ là thư mục thật. */
  writable() {
    return this.isSrv() || !!this.path;
  }
  send(op: string, extra: Record<string, unknown> = {}, ms?: number, onProgress?: (p: Progress) => void) {
    if (!this.src) return Promise.resolve<FsRes>({ ok: false, error: "Hãy chọn máy ở khung này trước." });
    return fsSend(this.src, op, extra, { ms, onProgress });
  }

  clear() {
    this.items = [];
    this.path = "";
    this.hist = [];
    this.sel = new Set();
    this.anchor = -1;
    this.renaming = null;
    this.status = { msg: "Chưa chọn máy.", err: false };
    this.emit();
  }

  // ------------------------------------------------------------------ điều hướng
  async go(path: string, noHist = false, opts: GoOpts = {}) {
    this.tBuf = "";
    this.tIdx = -1;
    if (!this.src) return this.st("Hãy chọn nguồn.", true);
    if (!noHist && this.path !== path) {
      // Lưu kèm VỊ TRÍ CUỘN + tên thư mục đang bước vào → Back quay lại ĐÚNG chỗ cũ
      const cur = this.path || "";
      const np = String(path || "");
      const ent: Hist = { p: cur, top: this.listEl?.scrollTop ?? 0, name: "" };
      if (cur && np.length > cur.length && np.toLowerCase().startsWith(cur.toLowerCase())) {
        ent.name = np.slice(cur.length).replace(/^[\\/]+/, "").replace(/[\\/]+$/, "");
        if (/[\\/]/.test(ent.name)) ent.name = ""; // không phải con TRỰC TIẾP → khỏi chọn
      } else if (!cur) {
        ent.name = np.replace(/[\\/]+$/, "") || np;
      }
      this.hist.push(ent);
    }
    const wantKeep = !!(opts.keepScroll || opts.selectNames?.length || opts.selectIndex != null);
    const keepTop = typeof opts.scrollTop === "number" ? opts.scrollTop : wantKeep ? this.listEl?.scrollTop ?? 0 : 0;
    const src = this.src;
    const my = ++this.reqSeq;
    this.st("⏳ Đang tải...");
    const res = await this.send("list", { path });
    if (src !== this.src || my !== this.reqSeq) return; // đã đổi nguồn / có lần tải mới hơn
    if (!res.ok) return this.st("❌ " + (res.error || "Lỗi"), true);
    this.path = res.path || "";
    this.items = this.sorted(res.items || []);
    this.sel = new Set();
    this.anchor = -1;
    this.renaming = null;
    let row = -1;
    const names = opts.selectNames?.map((n) => n.toLowerCase());
    if (names?.length) {
      const idxs = this.items.flatMap((it, i) => {
        const n = it.name.toLowerCase();
        return names.includes(n) || names.includes(n.replace(/[\\/]+$/, "")) ? [i] : [];
      });
      if (idxs.length) {
        this.sel = new Set(idxs);
        this.anchor = row = idxs[0];
      }
    } else if (opts.selectIndex != null && this.items.length) {
      row = Math.max(0, Math.min(opts.selectIndex, this.items.length - 1));
      this.sel = new Set([row]);
      this.anchor = row;
    }
    this.view = { seq: this.view.seq + 1, top: keepTop, row };
    this.status = { msg: this.summary(), err: false };
    this.emit();
  }

  /** Tải lại tại chỗ rồi báo kết quả (giữ chỗ cuộn + chọn các mục `names`). */
  async refreshKeep(msg: string, err: boolean, opts: GoOpts) {
    await this.go(this.path, true, { keepScroll: true, ...opts });
    if (msg) this.st(msg, err);
  }

  back() {
    const h = this.hist.pop();
    if (!h) return;
    this.sel = new Set();
    void this.go(h.p, true, { scrollTop: h.top || 0, selectNames: h.name ? [h.name] : undefined });
  }

  up() {
    if (!this.path) return;
    const p = this.path.replace(/[\\/]+$/, "");
    if (/^[A-Za-z]:$/.test(p)) return void this.go("");
    const i = Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"));
    if (i < 0) return void this.go("");
    let par = p.slice(0, i);
    if (/^[A-Za-z]:$/.test(par)) par += "\\";
    void this.go(par);
  }

  sorted(list: FsItem[]): FsItem[] {
    const k = this.sort;
    const d = this.desc ? -1 : 1;
    return [...list].sort((x, y) => {
      if ((x.type === "dir") !== (y.type === "dir")) return x.type === "dir" ? -1 : 1;
      const r = k === "size" ? (x.size || 0) - (y.size || 0)
        : k === "mtime" ? (x.mtime || 0) - (y.mtime || 0)
          : x.name.toLowerCase() < y.name.toLowerCase() ? -1 : 1;
      return r * d;
    });
  }

  setSort(k: SortKey) {
    this.desc = this.sort === k ? !this.desc : false;
    this.sort = k;
    this.items = this.sorted(this.items);
    this.sel = new Set();
    this.anchor = -1;
    this.emit();
  }

  // ------------------------------------------------------------------ chọn mục
  click(i: number, shift: boolean, ctrl: boolean) {
    if (shift && this.anchor >= 0) {
      const a = Math.min(this.anchor, i);
      const b = Math.max(this.anchor, i);
      if (!ctrl) this.sel = new Set();
      for (let k = a; k <= b; k++) this.sel.add(k);
    } else if (ctrl) {
      if (this.sel.has(i)) this.sel.delete(i);
      else this.sel.add(i);
      this.anchor = i;
    } else {
      this.sel = new Set([i]);
      this.anchor = i;
    }
    this.status = { msg: this.summary(), err: false };
    this.emit();
  }

  ensureSelected(i: number) {
    if (!this.sel.has(i)) {
      this.sel = new Set([i]);
      this.anchor = i;
      this.emit();
    }
  }

  selectAll() {
    this.sel = new Set(this.items.map((_, i) => i));
    this.anchor = this.items.length ? 0 : -1;
    this.status = { msg: this.summary(), err: false };
    this.emit();
  }

  open(i: number) {
    const it = this.items[i];
    if (it?.type === "dir") void this.go(this.full(it.name));
  }

  /** Gõ chữ để nhảy tới mục (như Explorer): cùng 1 chữ lặp lại → mục kế; gõ liền → nối chuỗi; ngừng 0,9 s → chuỗi mới. */
  typeAhead(ch: string) {
    const now = Date.now();
    if (!this.tBuf || now - this.tLast > 900) {
      this.tBuf = "";
      this.tIdx = -1;
    }
    this.tLast = now;
    const again = this.tBuf.length === 1 && this.tBuf.toLowerCase() === ch.toLowerCase();
    let from = 0;
    if (again) from = this.tIdx + 1;
    else this.tBuf += ch;
    const q = this.tBuf.toLowerCase();
    const n = this.items.length;
    for (let k = 0; k < n; k++) {
      const i = (((from + k) % n) + n) % n;
      if (this.items[i].name.toLowerCase().startsWith(q)) {
        this.tIdx = i;
        this.sel = new Set([i]);
        this.anchor = i;
        this.view = { seq: this.view.seq + 1, top: this.listEl?.scrollTop ?? 0, row: i };
        this.status = { msg: `⌨ "${this.tBuf}" → ${this.items[i].name}`, err: false };
        this.emit();
        return;
      }
    }
    if (n) this.st(`⌨ Không có mục nào bắt đầu bằng "${this.tBuf}"`, true);
  }

  resetTyping() {
    this.tBuf = "";
    this.tIdx = -1;
  }

  // ------------------------------------------------------------------ thao tác trong 1 khung
  async mkdir() {
    if (!this.src) return this.st("Chọn nguồn trước.", true);
    if (!this.writable()) return this.st("Vào một thư mục cụ thể trước.", true);
    const taken = new Set(this.items.map((i) => i.name.toLowerCase()));
    let n = "Thư mục mới";
    for (let i = 2; taken.has(n.toLowerCase()); i++) n = `Thư mục mới (${i})`;
    const r = await this.send("mkdir", { path: this.path, name: n });
    if (!r.ok) return this.st("❌ " + (r.error || "Lỗi tạo"), true);
    await this.go(this.path, true, { keepScroll: true, selectNames: [r.name || n] });
    this.startRename(); // đặt tên ngay tại dòng như Explorer
  }

  startRename() {
    if (this.sel.size !== 1) return this.st("Chọn đúng 1 mục để đổi tên.", true);
    this.renaming = [...this.sel][0];
    this.emit();
  }

  /** Enter / bấm ra ngoài = xác nhận · Esc = huỷ. */
  async finishRename(commit: boolean, value: string) {
    const idx = this.renaming;
    this.renaming = null;
    this.emit();
    const it = idx == null ? undefined : this.items[idx];
    if (!it) return;
    const v = value.trim();
    if (!commit || !v || v === it.name) return this.st("Đã huỷ đổi tên.");
    if (BAD_NAME.test(v)) return this.st('❌ Tên chứa ký tự không hợp lệ \\ / : * ? " < > |', true);
    const src = this.full(it.name);
    const dst = this.full(v);
    const r = await this.send("rename", { src, dst });
    if (!r.ok) return this.st("❌ " + (r.error || "Lỗi đổi tên"), true);
    this.undo.push({ list: [{ src: dst, dst: src }] });
    this.redo = [];
    await this.refreshKeep(`✅ Đã đổi tên thành "${v}".`, false, { selectNames: [v] });
  }

  /** Delete = Thùng rác · Shift+Delete = xoá vĩnh viễn. KHÔNG hỏi lại — như Explorer (hệ cũ cũng vậy). */
  async del(perm: boolean) {
    const s = this.selItems();
    if (!s.length) return this.st("Chọn mục cần xoá.", true);
    const idxAfter = Math.min(...this.sel);
    this.st(perm ? "⏳ Đang xoá vĩnh viễn..." : "⏳ Đang chuyển vào Thùng rác...");
    const rs = await pool(s, 4, (it) => this.send(perm ? "delete" : "recycle", { target: this.full(it.name) }));
    const bad = rs.filter((r) => !r.ok);
    const msg = bad.length ? `⚠️ Xong, ${bad.length} lỗi: ${bad[0].error ?? ""}`
      : `${perm ? "✅ Đã xoá vĩnh viễn" : "🗑️ Đã vào Thùng rác"} ${rs.length} mục.`;
    await this.refreshKeep(msg, bad.length > 0, { selectIndex: idxAfter });
  }

  mark(mode: "cut" | "copy") {
    const s = this.selItems();
    if (!s.length) return this.st("Chọn mục trước.", true);
    this.clip = { mode, items: s.map((i) => ({ name: i.name, type: i.type })), dir: this.path, src: this.src };
    this.st(`${mode === "cut" ? "✂️ Đã cắt" : "📑 Đã sao chép"} ${s.length} mục — vào thư mục đích rồi Ctrl+V.`);
  }

  isCut(name: string) {
    const c = this.clip;
    return !!c && c.mode === "cut" && c.src === this.src && c.dir === this.path && c.items.some((x) => x.name === name);
  }

  async paste() {
    const c = this.clip;
    if (!c?.items.length) return this.st("Chưa cắt/sao chép gì.", true);
    if (c.src !== this.src) return this.st("Bộ nhớ tạm thuộc nguồn khác — kéo-thả giữa 2 khung để chép.", true);
    if (!this.writable()) return this.st("Vào một thư mục cụ thể để dán.", true);
    const sd = c.dir.replace(/[\\/]+$/, "");
    const dd = this.path.replace(/[\\/]+$/, "");
    const same = sd === dd;
    const isCopy = c.mode === "copy";
    if (!isCopy && same) return this.st("Cắt rồi dán cùng thư mục không có tác dụng.", true);
    this.st(`⏳ Đang ${isCopy ? "sao chép" : "di chuyển"} ${c.items.length} mục...`);
    const landed: string[] = [];
    const undoL: Move[] = [];
    const rs = await pool(c.items, 4, async (it) => {
      const dn = isCopy && same ? copyName(it.name, it.type === "dir") : it.name;
      const src = join(sd, it.name);
      const dst = join(dd, dn);
      const r = await this.send(isCopy ? "copy" : "rename", { src, dst }, 120000);
      if (r.ok) {
        landed.push(dn);
        if (!isCopy) undoL.push({ src: dst, dst: src });
      }
      return r;
    });
    const bad = rs.filter((r) => !r.ok).length;
    if (!isCopy && undoL.length) {
      this.undo.push({ list: undoL });
      this.redo = [];
      this.clip = null;
    }
    const msg = bad ? `⚠️ Xong, ${bad} lỗi (khác ổ đĩa / trùng tên?).`
      : `${isCopy ? "📑 Đã sao chép" : "✅ Đã di chuyển"} ${rs.length} mục.`;
    await this.refreshKeep(msg, bad > 0, { selectNames: landed });
  }

  /** Kéo-thả trong CÙNG khung = chuyển vào thư mục con (ghi hoàn tác được, như Cắt/Dán). */
  async moveInto(items: FsItem[], dirName: string) {
    const dstDir = this.full(dirName);
    const list = items.filter((it) => it.name !== dirName);
    if (!list.length) return;
    this.st(`⏳ Đang chuyển ${list.length} mục vào "${dirName}"...`);
    const undoL: Move[] = [];
    let err = "";
    const rs = await pool(list, 4, async (it) => {
      const src = this.full(it.name);
      const dst = join(dstDir, it.name);
      const r = await this.send("rename", { src, dst }, 120000);
      if (r.ok) undoL.push({ src: dst, dst: src });
      else err ||= r.error ?? "";
      return r;
    });
    if (undoL.length) {
      this.undo.push({ list: undoL });
      this.redo = [];
    }
    const bad = rs.filter((r) => !r.ok).length;
    await this.refreshKeep(bad ? `⚠️ Xong, ${bad} lỗi${err ? ": " + err : " (trùng tên?)."}`
      : `✅ Đã chuyển ${list.length} mục vào "${dirName}".`, bad > 0, { selectNames: [dirName] });
  }

  private async applyMoves(list: Move[]): Promise<number> {
    const rs = await pool(list, 4, (r) => this.send("rename", { src: r.src, dst: r.dst }));
    return rs.filter((x) => !x.ok).length;
  }

  async undoAct(redo = false) {
    const from = redo ? this.redo : this.undo;
    const to = redo ? this.undo : this.redo;
    const a = from.pop();
    if (!a) return this.st(redo ? "Không có gì để làm lại." : "Không có gì để hoàn tác.", true);
    this.st(redo ? "↷ Đang làm lại..." : "↶ Đang hoàn tác...");
    const f = await this.applyMoves(a.list);
    to.push({ list: a.list.map((r) => ({ src: r.dst, dst: r.src })) });
    const what = redo ? "Làm lại" : "Hoàn tác";
    await this.refreshKeep(f ? `⚠️ ${what} xong, ${f} lỗi.` : `✅ Đã ${what.toLowerCase()}.`, f > 0,
      { selectNames: a.list.map((r) => base(r.dst)) });
  }

  // ------------------------------------------------------------------ thuộc tính
  async props() {
    const s = this.selItems();
    if (s.length !== 1) return this.st("Chọn đúng 1 mục để xem thuộc tính.", true);
    const it = s[0];
    const short = (note = "", err = false) => {
      this.win.showProps({ name: it.name, type: it.type, location: this.path, size: it.size, disk: it.size,
        modified: it.mtime, src: this.label() });
      if (note) this.st(note, err);
    };
    if (this.isSrv()) return short();
    this.st(`⏳ Đang lấy thuộc tính "${it.name}"...`);
    const r = await propsViaPS(this.src, this.full(it.name));
    if (!r?.ok || !r.props) return short(r?.error ? "⚠️ " + r.error : "Hiện thuộc tính rút gọn.", !!r?.error);
    this.win.showProps({ ...r.props, name: r.props.name || it.name, type: r.props.type || it.type, src: this.label() });
    this.st(this.summary());
  }

  // ------------------------------------------------------------------ máy bạn ↔ khung
  /** Về máy tôi: hỏi chỗ lưu TRƯỚC (còn trong thao tác bấm), rồi lấy tệp từ nguồn, ghi thẳng ra đĩa theo luồng. */
  async toMyPC() {
    const s = this.selItems().filter((i) => i.type !== "dir");
    if (!s.length) return this.st("Chọn ít nhất 1 TỆP (thư mục: kéo-thả sang khung kia).", true);
    let sink;
    try {
      sink = await pickSink(s.map((i) => i.name));
    } catch (e) {
      return this.st("❌ " + (e as Error).message, true);
    }
    if (!sink) return this.st("Đã huỷ tải về.");
    for (const it of s) {
      const q = this.win.queue(it.name, `${this.label()} → máy bạn`);
      try {
        const write = await sink(it.name);
        let url = srvFilePath(this.full(it.name));
        if (!this.isSrv()) {
          const tok = await newToken();
          const r = await this.send("pull", { target: this.full(it.name), token: tok }, LONG, q.tick);
          if (!r.ok) throw new Error(r.error || "Máy trạm không nộp được tệp");
          url = pulledPath(tok);
        }
        const res = await authFetch(url);
        if (!res.ok) throw new Error(`Tải lỗi ${res.status}`);
        await write(res);
        q.done();
        this.st(`✅ Đã tải "${it.name}" về máy bạn.`);
      } catch (e) {
        q.fail((e as Error).message);
        this.st("❌ " + (e as Error).message, true);
      }
    }
  }

  async uploadFromPC(files: File[], into = "") {
    if (!this.src) return this.st("Chọn nguồn trước.", true);
    if (!into && !this.writable()) return this.st("Vào một thư mục cụ thể (không phải danh sách ổ đĩa).", true);
    const list = files.filter((f) => f.size > 0 || f.type !== ""); // thư mục kéo từ Explorer = mục rỗng không kiểu
    if (!list.length) return this.st("Chỉ tải lên được TỆP (thư mục: nén .zip trước, như hệ cũ).", true);
    const upDir = into || this.path;
    for (const f of list) {
      const q = this.win.queue(f.name, `máy bạn → ${this.label()}`);
      this.st(`⏳ Đang tải lên "${f.name}"...`);
      let r: FsRes;
      if (this.isSrv()) {
        r = await srvUpload(upDir, f, f.name);
      } else {
        try {
          const u = await putFile(f, f.name);
          r = await this.send("push", { folder: upDir, filename: u.filename, download_url: `/fs_serve/${u.token}`,
            unzip: false }, LONG, q.tick);
        } catch (e) {
          r = { ok: false, error: (e as Error).message };
        }
      }
      if (r.ok) q.done();
      else q.fail(r.error);
    }
    await this.refreshKeep("✅ Đã tải lên xong.", false,
      { selectNames: into ? [base(into)] : list.map((f) => f.name) });
  }

  // ------------------------------------------------------------------ truyền giữa hai khung
  async sendTo(dst: FsPane, items?: FsItem[], into = "") {
    const s = items?.length ? items : this.selItems();
    if (!s.length) return this.st("Chọn mục cần chép.", true);
    if (!dst.src) return dst.st("Chọn nguồn ở khung đích.", true);
    if (!into && !dst.writable()) return dst.st("Vào một thư mục cụ thể ở khung đích (hoặc kéo thẳng vào 1 thư mục).",
      true);
    if (dst.src === this.src) return this.st("Hai khung đang cùng một nguồn — dùng Ctrl+C / Ctrl+V.", true);
    for (const it of s) await this.one(dst, it, into);
    await dst.refreshKeep("", false, { selectNames: into ? [base(into)] : s.map((it) => it.name) });
  }

  private async one(dst: FsPane, it: FsItem, into: string) {
    const dpath = into || dst.path;
    const src = this.full(it.name);
    const two = !this.isSrv() && !dst.isSrv(); // trạm → trạm = 2 chặng
    const q = this.win.queue(it.name, `${this.label()} → ${dst.label()}${into ? " \\" + base(into) : ""}` +
      (it.type === "dir" ? " (nén .zip)" : ""), two ? 2 : 1);
    try {
      if (this.isSrv()) { // Máy chủ → máy trạm: bày ra token, agent tự tải (không qua Desktop)
        const r = await this.send("stage", { target: src });
        if (!r.ok || !r.token) throw new Error(r.error || "Không bày tệp ra được");
        const x = await dst.send("push", { folder: dpath, filename: r.filename, download_url: `/fs_serve/${r.token}`,
          unzip: !!r.zipped }, LONG, q.tick);
        if (!x.ok) throw new Error(x.error);
        return q.done();
      }
      const tok = await newToken(); // máy trạm → …: agent nộp lên Core theo token trước
      const r = await this.send("pull", { target: src, token: tok }, LONG, q.tick);
      if (!r.ok) throw new Error(r.error || "Máy nguồn không nộp được");
      let x: FsRes;
      if (dst.isSrv()) {
        x = await dst.send("land", { token: tok, folder: dpath, filename: r.name, zipped: !!r.zipped });
      } else { // → máy trạm khác: máy B tải thẳng từ cầu nối /fs_bridge
        q.half();
        x = await dst.send("push", { folder: dpath, filename: r.name, download_url: `/fs_bridge/${tok}`,
          unzip: !!r.zipped }, LONG, q.tick);
      }
      if (!x.ok) throw new Error(x.error);
      q.done();
    } catch (e) {
      q.fail((e as Error).message);
    }
  }
}

// ====================================================================== CỬA SỔ 2 KHUNG
export class FsWindow extends Store {
  panes: [FsPane, FsPane];
  machines: Machine[] = [];
  info: Info = { super: false, self_device: null };
  focused: FsPane;
  rows: QRow[] = [];
  propsData: Props | null = null;
  drag: { from: FsPane; items: FsItem[] } | null = null;
  private qSeq = 0;

  constructor() {
    super();
    this.panes = [new FsPane(this, "L"), new FsPane(this, "R")];
    this.focused = this.panes[0];
  }

  hostName(id: string): string {
    return id === SRV ? "Máy chủ" : this.machines.find((m) => m.id === id)?.hostname ?? "";
  }

  focus(p: FsPane) {
    if (this.focused !== p) {
      this.focused = p;
      this.emit();
    }
  }

  /** Danh sách máy mới (poll 15 s): máy đang mở ở một khung mà vừa offline → GIỮ lại kèm ghi chú, không đá người dùng ra. */
  setMachines(ms: Machine[]) {
    const out = ms.filter((m) => m.is_online);
    for (const p of this.panes) {
      if (p.src && p.src !== SRV && !out.some((m) => m.id === p.src)) {
        const old = ms.find((m) => m.id === p.src) ?? this.machines.find((m) => m.id === p.src);
        if (old) out.push({ ...old, is_online: false, kept: true });
      }
    }
    this.machines = out;
    this.emit();
    this.panes.forEach((p) => p.emit());
  }

  /** Nguồn chọn được cho một khung: KHÔNG gồm nguồn khung kia đang mở; "Máy chủ" chỉ Super Admin. */
  options(p: FsPane): { value: string; label: string }[] {
    const taken = p.other().src;
    const out = [{ value: "", label: "— Chọn máy —" }];
    if (this.info.super && taken !== SRV) out.push({ value: SRV, label: "🖥️ Máy chủ (kho của tổ chức)" });
    for (const m of this.machines) {
      if (m.id === taken) continue;
      out.push({ value: m.id, label: m.hostname + (m.id === this.info.self_device?.id ? " (máy này)" : "") +
        (m.kept ? " — đã offline" : "") });
    }
    return out;
  }

  /** Đổi nguồn; khung kia đang mở đúng nguồn đó → HOÁN ĐỔI (nhận nguồn cũ của khung vừa đổi). */
  choose(p: FsPane, src: string, startPath = "") {
    const oth = p.other();
    p.prevSrc = p.src;
    p.src = src;
    p.hist = [];
    p.sel = new Set();
    p.path = "";
    if (oth.src && oth.src === src) {
      oth.src = p.prevSrc;
      oth.hist = [];
      oth.path = "";
      oth.sel = new Set();
      if (oth.src) void oth.go("");
      else oth.clear();
    }
    this.emit();
    if (src) void p.go(startPath);
    else p.clear();
  }

  title() {
    return `Trình quản lý tệp · ${this.panes[0].label()}  ⇄  ${this.panes[1].label()}`;
  }

  /** Một dòng trong hàng đợi truyền: tick (fs_progress) · half (trạm→trạm: đã lên Core) · done · fail. */
  queue(name: string, route: string, hops = 1) {
    const row: QRow = { id: ++this.qSeq, name, route, pct: 0, label: "đang chờ…", state: "run" };
    this.rows = [...this.rows.slice(-49), row];
    const span = 100 / hops;
    let baseP = 0;
    const set = (patch: Partial<QRow>) => {
      Object.assign(row, patch);
      this.rows = [...this.rows];
      this.emit();
    };
    set({});
    return {
      tick: (p: Progress) => {
        if (!p.total) return;
        const pc = Math.min(100, Math.round((p.sent * 100) / p.total));
        set({ pct: baseP + (pc * span) / 100, label: `${pc}% · ${human(p.sent)} / ${human(p.total)}` });
      },
      half: () => {
        baseP = 50;
        set({ pct: 50, label: "đã lên máy chủ — đang đẩy sang máy đích..." });
      },
      done: () => set({ pct: 100, label: "hoàn tất", state: "ok" }),
      fail: (e?: string) => set({ pct: 100, label: "lỗi: " + (e || "?"), state: "err" }),
    };
  }

  showProps(p: Props | null) {
    this.propsData = p;
    this.emit();
  }
}

// ====================================================================== thuộc tính qua PowerShell (như hệ cũ)
// Agent KHÔNG có lệnh 'props' → dùng đường PowerShell hàng loạt của Core (quyền SYSTEM) cho đúng 1 máy.
// $ProgressPreference bắt buộc: Invoke-* ghi luồng progress làm rò '#< CLIXML' hỏng JSON.
async function propsViaPS(deviceId: string, target: string): Promise<{ ok: boolean; error?: string;
  props?: Omit<Props, "src"> } | null> {
  const q = (s: string) => String(s ?? "").replace(/'/g, "''");
  const script = "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';try{" +
    `$t='${q(target)}';$ep=Get-Date '1970-01-01';$i=Get-Item -LiteralPath $t -Force;` +
    "$e=@{name=$i.Name;path=$i.FullName;" +
    "location=$(if($i.PSObject.Properties['Parent'] -and $i.Parent){$i.Parent.FullName}else{Split-Path $i.FullName -Parent});" +
    "created=[int64]((New-TimeSpan -Start $ep -End $i.CreationTimeUtc).TotalSeconds);" +
    "modified=[int64]((New-TimeSpan -Start $ep -End $i.LastWriteTimeUtc).TotalSeconds);" +
    "accessed=[int64]((New-TimeSpan -Start $ep -End $i.LastAccessTimeUtc).TotalSeconds);" +
    "attrs=[string]$i.Attributes};" +
    "if($i.PSIsContainer){" +
    "$fs=@(Get-ChildItem -LiteralPath $t -Recurse -Force -File -ErrorAction SilentlyContinue);" +
    "$ds=@(Get-ChildItem -LiteralPath $t -Recurse -Force -Directory -ErrorAction SilentlyContinue);" +
    "$sum=0;$alloc=0;foreach($x in $fs){$sum+=$x.Length;$alloc+=[math]::Ceiling($x.Length/4096)*4096};" +
    "$e['type']='dir';$e['size']=[int64]$sum;$e['disk']=[int64]$alloc;$e['files']=$fs.Count;$e['folders']=$ds.Count}" +
    "else{$e['type']='file';$e['size']=[int64]$i.Length;" +
    "$e['disk']=[int64]([math]::Ceiling($i.Length/4096)*4096);$e['ext']=$i.Extension};" +
    "(@{ok=$true;props=$e}|ConvertTo-Json -Compress -Depth 4)" +
    "}catch{(@{ok=$false;error=[string]$_.Exception.Message}|ConvertTo-Json -Compress)}";
  const pick = (txt?: string) => { // dòng JSON hợp lệ CUỐI CÙNG (bỏ mọi rác PowerShell)
    const lines = String(txt ?? "").replace(/\r/g, "").split("\n");
    for (let i = lines.length - 1; i >= 0; i--) {
      const s = lines[i].trim();
      if (!s.startsWith("{")) continue;
      try {
        return JSON.parse(s);
      } catch {
        // dòng hỏng → thử dòng trên
      }
    }
    return null;
  };
  try {
    const r = await authFetch("/api/terminal/bulk", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_ids: [deviceId], room_id: null, exclude_gv: false, script, timeout: 30 }) });
    if (!r.ok) return null;
    const { token } = (await r.json()) as { token: string };
    for (let tries = 0; tries < 40; tries++) {
      await new Promise((ok) => setTimeout(ok, tries === 0 ? 400 : 800));
      const st = await authFetch(`/api/terminal/bulk/${token}`);
      if (!st.ok) continue;
      const j = (await st.json()) as { results: { status: string; stdout?: string; stderr?: string }[] };
      const mine = j.results?.[0];
      if (!mine || mine.status === "running") continue;
      return pick(mine.stdout) ?? pick(mine.stderr);
    }
  } catch {
    // mạng chớp → thuộc tính rút gọn
  }
  return null;
}
