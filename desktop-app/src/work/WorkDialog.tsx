// Giao bài / thu bài / tệp đã giao (Sổ tay 7.3) — một hộp thoại cho 3 nơi mở: trang phòng (1 phòng), thanh "Đã chọn N
// máy" (đúng các máy đó), trang Phòng máy (NHIỀU phòng — như panel "Truyền tệp" trang chủ hệ cũ).
// Mang từ hệ cũ: chọn tệp HOẶC cả thư mục (giữ cây thư mục con); đích trống = Desktop chung; ghi đè tuỳ chọn; kết quả
// TỪNG máy kèm lý do; thu bài lưu thẳng vào <thư mục>/<phòng>/<máy>/… ngay khi máy nộp; nhật ký thu có nút sao chép;
// nhật ký tệp đã giao + xoá (máy tắt → tự xoá khi online lại).
// Bài học 18b: vừa nghe sự kiện realtime (send_report / collect_upload / collect_report) vừa POLL — không chỉ một đường.
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { authFetch, getJson } from "../api-client";
import type { ListResult, Room } from "../api-client/types";
import { pickSink } from "../files/transport";
import { human } from "../files/pane";
import { realtime, request } from "../realtime-client";
import { useSession } from "../session/store";
import { Modal } from "../shared/ui";
import * as W from "./api";
import { CollectLog, statusText } from "./CollectLog";

export type WorkPreset = {
  rooms?: { id: string; name: string }[]; // phòng mở sẵn (trang phòng) / chọn sẵn (trang Phòng máy)
  deviceIds?: string[]; // giao/thu đúng các máy này (thanh "Đã chọn N máy")
  deviceNames?: string[];
  pickRooms?: boolean; // cho chọn nhiều phòng
};
type Tab = "send" | "collect" | "pushed";

export function WorkDialog({ preset, onClose }: { preset: WorkPreset; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("send");
  const session = useSession((s) => s.session);
  const limited = !!session && !session.is_super && session.room_ids.length > 0;
  const byDevices = !!preset.deviceIds?.length;
  const roomsQ = useQuery({ queryKey: ["rooms"], queryFn: () => getJson<ListResult<Room>>("/api/rooms"),
    enabled: !!preset.pickRooms });
  const [roomSel, setRoomSel] = useState<Set<string>>(() => new Set((preset.rooms ?? []).map((r) => r.id)));
  const [mode, setMode] = useState<W.Mode>("students");
  const [busy, setBusy] = useState(false);
  const nameOf = (id: string) => preset.rooms?.find((r) => r.id === id)?.name ??
    roomsQ.data?.items.find((r) => r.id === id)?.name ?? id;
  const target: W.Target = byDevices ? { room_ids: [], device_ids: preset.deviceIds ?? [], mode: "all" }
    : { room_ids: [...roomSel], device_ids: [], mode };
  const what = byDevices ? (preset.deviceNames?.length === 1 ? preset.deviceNames[0] : `${preset.deviceIds?.length} máy đã chọn`)
    : roomSel.size === 1 ? nameOf([...roomSel][0]) : roomSel.size ? `${roomSel.size} phòng` : "chưa chọn phòng";
  const ready = byDevices || roomSel.size > 0;
  const roomNames = byDevices ? (preset.rooms ?? []).map((r) => r.name) : [...roomSel].map(nameOf);

  return (
    <Modal title={`Giao bài / thu bài — ${what}`} onClose={onClose} busy={busy} wide>
      <div className="wk-head">
        <div className="seg" role="tablist" aria-label="Chức năng">
          {([["send", "⬇ Giao bài"], ["collect", "⬆ Thu bài"], ["pushed", "🗂 Tệp đã giao"]] as [Tab, string][]).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
              {l}
            </button>
          ))}
        </div>
        {!byDevices && tab !== "pushed" && (
          <label className="wk-mode">Đối tượng
            <select value={mode} onChange={(e) => setMode(e.target.value as W.Mode)}>
              <option value="students">Máy sinh viên</option>
              <option value="teachers">Máy giảng viên</option>
              <option value="all">Tất cả máy</option>
            </select>
          </label>
        )}
      </div>
      {preset.pickRooms && tab !== "pushed" && (
        <RoomPicker rooms={roomsQ.data?.items ?? []} sel={roomSel} setSel={setRoomSel} loading={roomsQ.isPending} />
      )}
      <div hidden={tab !== "send"}><SendTab target={target} ready={ready} setBusy={setBusy} /></div>
      <div hidden={tab !== "collect"}><CollectTab target={target} ready={ready} limited={limited} what={what} /></div>
      <div hidden={tab !== "pushed"}><PushedTab active={tab === "pushed"} roomIds={byDevices ? [] : [...roomSel]}
                                               roomIdsOfDevices={(preset.rooms ?? []).map((r) => r.id)}
                                               roomNames={roomNames} /></div>
      <div className="actions wk-close"><button className="ghost" onClick={onClose} disabled={busy}>Đóng</button></div>
    </Modal>
  );
}

function RoomPicker({ rooms, sel, setSel, loading }: {
  rooms: Room[]; sel: Set<string>; setSel: (s: Set<string>) => void; loading: boolean;
}) {
  const official = rooms.filter((r) => r.official);
  const all = official.length > 0 && official.every((r) => sel.has(r.id));
  const flip = (id: string) => {
    const n = new Set(sel);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    setSel(n);
  };
  if (loading) return <p className="muted">Đang tải danh sách phòng…</p>;
  return (
    <div className="wk-rooms">
      <label className="check"><input type="checkbox" checked={all}
                                      onChange={() => setSel(all ? new Set() : new Set(official.map((r) => r.id)))} />
        <b>Chọn mọi phòng</b></label>
      <div className="list">
        {official.map((r) => (
          <label key={r.id} className={`check${sel.has(r.id) ? " on" : ""}`}>
            <input type="checkbox" checked={sel.has(r.id)} onChange={() => flip(r.id)} />
            {r.name} <small className="muted">{r.online}/{r.total}</small>
          </label>
        ))}
      </div>
    </div>
  );
}

/** Nghe kết quả realtime của một phiên (room `res:<sid>`) + poll đều — gọi `refresh` mỗi khi có tin. */
function useLive(sid: string | null, events: string[], refresh: () => Promise<boolean>, every = 2000) {
  const fn = useRef(refresh);
  fn.current = refresh;
  useEffect(() => {
    if (!sid) return;
    let stop = false;
    const poll = () => void fn.current().then((done) => {
      if (done && !stop) window.clearInterval(t);
    }).catch(() => undefined);
    void request("subscribe_result", { token: sid });
    const s = realtime();
    const on = (p: { session_id?: string }) => {
      if (p?.session_id === sid) poll();
    };
    events.forEach((e) => s?.on(e, on));
    const t = window.setInterval(poll, every);
    poll();
    return () => {
      stop = true;
      window.clearInterval(t);
      events.forEach((e) => s?.off(e, on));
    };
  }, [sid]); // eslint-disable-line react-hooks/exhaustive-deps -- events/every cố định theo nơi gọi
}

const reasons = (sk: W.Skipped[]) => sk.length > 0 && (
  <details>
    <summary>Bỏ qua {sk.length} máy</summary>
    <ul className="small">{sk.map((s, i) => <li key={i}>{s.hostname ?? s.id} — {s.reason}</li>)}</ul>
  </details>
);

// ====================================================================== GIAO BÀI
const SEND_LABEL: Record<W.SendRow["status"], string> = {
  running: "⏳ Đang nhận…", timeout: "⌛ Chưa báo (mất mạng / agent không chạy?)", ok: "✔", partial: "⚠", fail: "✖",
};

function SendTab({ target, ready, setBusy }: { target: W.Target; ready: boolean; setBusy: (b: boolean) => void }) {
  const [items, setItems] = useState<{ file: File; name: string }[]>([]);
  const [folder, setFolder] = useState("");
  const [dest, setDest] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [phase, setPhase] = useState<"idle" | "upload" | "send" | "run">("idle");
  const [sentBytes, setSentBytes] = useState(0);
  const [err, setErr] = useState("");
  const [run, setRun] = useState<{ sid: string; skipped: W.Skipped[]; total: number } | null>(null);
  const [st, setSt] = useState<W.SendStatus | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const total = items.reduce((a, b) => a + b.file.size, 0);

  useLive(run?.sid ?? null, ["send_report"], async () => {
    const s = await W.sendStatus(run!.sid);
    setSt(s);
    return s.complete;
  }, 1500);

  const pick = (fl: FileList | null, isDir: boolean) => {
    const arr = Array.from(fl ?? []);
    // Chọn tệp và chọn thư mục LOẠI TRỪ nhau (như chonthumuc.js hệ cũ); thư mục giữ đường dẫn con
    setItems(arr.map((f) => ({ file: f, name: isDir ? f.webkitRelativePath || f.name : f.name })));
    setFolder(isDir && arr[0] ? (arr[0].webkitRelativePath || "").split("/")[0] : "");
    if (isDir && fileRef.current) fileRef.current.value = "";
    if (!isDir && dirRef.current) dirRef.current.value = "";
  };

  async function go() {
    setErr("");
    setRun(null);
    setSt(null);
    setOpen(null);
    setBusy(true);
    setPhase("upload");
    try {
      let batch = "";
      let done = 0;
      for (const it of items) {
        const r = await W.uploadOne(it.file, it.name, batch, (s) => setSentBytes(done + s));
        batch = r.batch_id;
        done += it.file.size;
        setSentBytes(done);
      }
      setPhase("send");
      const r = await W.startSend({ ...target, batch_id: batch, dest_folder: dest.trim(), overwrite });
      setRun({ sid: r.session_id, skipped: r.skipped, total: r.total });
      setPhase("run");
      if (!r.total) setErr("Không có máy nào đang bật để nhận bài.");
    } catch (e) {
      setErr((e as Error).message);
      setPhase("idle");
    } finally {
      setBusy(false);
    }
  }

  const working = phase === "upload" || phase === "send";
  return (
    <div className="form wk-pane">
      <div className="wk-pick">
        <button type="button" className="ghost" onClick={() => dirRef.current?.click()} disabled={working}>
          📁 Chọn thư mục…</button>
        <button type="button" className="ghost" onClick={() => fileRef.current?.click()} disabled={working}>
          📄 Chọn tệp…</button>
        <input ref={fileRef} type="file" multiple hidden onChange={(e) => pick(e.currentTarget.files, false)} />
        <input ref={dirRef} type="file" hidden onChange={(e) => pick(e.currentTarget.files, true)}
               {...({ webkitdirectory: "" } as Record<string, string>)} />
      </div>
      <p className="muted small wk-picked">
        {items.length ? <>Đang chọn: <b>{folder ? `thư mục "${folder}"` : `${items.length} tệp`}</b>
          {folder && ` (${items.length} tệp)`} · {human(total)}</> : "Chưa chọn tệp hoặc thư mục nào."}
      </p>
      <label>Thư mục đích trên máy trạm
        <input value={dest} onChange={(e) => setDest(e.target.value)} disabled={working}
               placeholder="Để trống = Desktop chung (C:\Users\Public\Desktop). VD: C:\BaiTap" />
      </label>
      <label className="check"><input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)}
                                      disabled={working} />
        Ghi đè nếu máy trạm đã có tệp trùng tên (bỏ tích = giữ tệp cũ, bỏ qua)</label>
      {err && <p className="error">{err}</p>}
      <div className="actions">
        <button onClick={() => void go()} disabled={working || !items.length || !ready}>
          {phase === "upload" ? `Đang tải lên ${total ? Math.floor((sentBytes * 100) / total) : 0}%…`
            : phase === "send" ? "Đang phát lệnh…" : "Giao xuống các máy đang bật"}
        </button>
      </div>
      {phase === "upload" && <div className="wk-bar"><i style={{ width: `${total ? (sentBytes * 100) / total : 0}%` }} /></div>}
      {run && (
        <div className="ctl-res">
          <p>{st ? <>Đã báo <b>{st.finished}</b> / {st.total} máy → <code>{st.dest_dir}</code>
            {st.overwrite ? " (ghi đè)" : ""}{!st.complete && ` · chờ tối đa ${st.deadline_s} giây`}</>
            : `Đã gửi tới ${run.total} máy…`}</p>
          <table className="grid bulk-res wk-res">
            <thead><tr><th>Máy</th><th>Phòng</th><th>Kết quả</th></tr></thead>
            <tbody>
              {(st?.results ?? []).map((r) => (
                <tr key={r.hostname} className={open === r.hostname ? "sel" : ""}
                    onClick={() => setOpen(open === r.hostname ? null : r.hostname)}>
                  <td>{r.hostname}</td>
                  <td className="muted">{r.room_name}</td>
                  <td className={r.status === "ok" ? "ok-text" : r.status === "partial" || r.status === "running"
                    ? "warn-text" : "danger-text"}>
                    {SEND_LABEL[r.status]}{r.status === "ok" || r.status === "partial" || r.status === "fail"
                      ? ` nhận ${r.saved ?? 0} tệp${r.skipped ? `, bỏ qua ${r.skipped} (đã có)` : ""}` +
                        `${r.failed ? `, lỗi ${r.failed}` : ""}${r.reason ? ` — ${r.reason}` : ""}` : ""}
                    {open === r.hostname && (r.files ?? []).length > 0 && (
                      <ul className="small wk-files">
                        {(r.files ?? []).map((f) => (
                          <li key={f.name} className={f.ok ? "ok-text" : "danger-text"}>
                            {f.ok ? "✔" : "✖"} {f.name}{f.note ? ` (${f.note})` : ""}{f.error ? ` — ${f.error}` : ""}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {reasons(run.skipped)}
          {st?.complete && (
            <div className="actions"><button className="ghost" onClick={() => {
              setRun(null);
              setSt(null);
              setItems([]);
              setFolder("");
              setPhase("idle");
            }}>Giao lô khác</button></div>
          )}
        </div>
      )}
    </div>
  );
}

// ====================================================================== THU BÀI
const BADGE: Record<W.CollectRow["status"], string> = {
  running: "warn", ok: "ok", nofile: "warn", nofolder: "err", fail: "err", offline: "err",
};

function CollectTab({ target, ready, limited, what }: {
  target: W.Target; ready: boolean; limited: boolean; what: string;
}) {
  const [src, setSrc] = useState("");
  const [pat, setPat] = useState("*");
  const [del, setDel] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [thu, setThu] = useState(false);
  const [ca, setCa] = useState("");
  const [dir, setDir] = useState<W.DirHandle | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<{ sid: string; skipped: W.Skipped[]; ca: string } | null>(null);
  const [st, setSt] = useState<W.CollectStatus | null>(null);
  const [local, setLocal] = useState<Record<string, string>>({}); // máy → đã lưu về máy bạn ở đâu / lỗi
  const [log, setLog] = useState(false);
  const saving = useRef(new Set<string>());
  const chain = useRef(Promise.resolve());
  const shown = useRef(false);

  useLive(run?.sid ?? null, ["collect_upload", "collect_report"], async () => {
    const s = await W.collectStatus(run!.sid);
    setSt(s);
    return s.complete;
  });

  // Máy vừa nộp → lưu NGAY vào <thư mục>/<phòng>/<máy>/… (lần lượt từng máy, không dội máy chủ)
  useEffect(() => {
    if (!st || !dir) return;
    for (const r of st.results) {
      if (!r.has_zip || saving.current.has(r.hostname)) continue;
      saving.current.add(r.hostname);
      chain.current = chain.current.then(async () => {
        try {
          const n = await W.saveHost(dir, st.session_id, r);
          setLocal((m) => ({ ...m, [r.hostname]: `${dir.name}/${r.room_name || "Khac"}/${r.hostname} (${n} tệp)` }));
        } catch (e) {
          saving.current.delete(r.hostname); // lượt poll sau thử lại
          setLocal((m) => ({ ...m, [r.hostname]: "lỗi: " + (e as Error).message }));
        }
      });
    }
  }, [st, dir]);

  useEffect(() => { // xong → tự mở nhật ký thu (như hệ cũ)
    if (st?.complete && !shown.current) {
      shown.current = true;
      setLog(true);
    }
  }, [st?.complete]);

  async function go() {
    if (del && !confirmDel) return setConfirmDel(true);
    setErr("");
    setConfirmDel(false);
    setBusy(true);
    setRun(null);
    setSt(null);
    setLocal({});
    saving.current = new Set();
    shown.current = false;
    try {
      const r = await W.startCollect({ ...target, src_folder: src.trim(),
        patterns: pat.split(",").map((s) => s.trim()).filter(Boolean), delete_after: del, save_thu: thu, ca });
      setRun({ sid: r.session_id, skipped: r.skipped, ca: r.ca });
      if (!r.expected) setErr("Không có máy nào để thu (phòng chưa có máy bật / chưa giao bài).");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function download(path: string, name: string) {
    setErr("");
    try {
      const sink = await pickSink([name]);
      if (!sink) return;
      const write = await sink(name);
      const res = await authFetch(path);
      if (!res.ok) throw new Error(`Tải lỗi ${res.status}`);
      await write(res);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const sid = run?.sid ?? "";
  return (
    <div className="form wk-pane">
      <label>Thư mục nguồn trên máy trạm (nơi có bài làm)
        <input value={src} onChange={(e) => setSrc(e.target.value)} placeholder="VD: C:\Users\Public\Desktop\BaiTap" />
      </label>
      <label>Loại tệp
        <input value={pat} onChange={(e) => setPat(e.target.value)} placeholder="* = tất cả; hoặc *.docx, *.pdf, *.cpp" />
      </label>
      <div className="wk-pick">
        <button type="button" className="ghost" onClick={() => void W.pickDir().then((d) => d && setDir(d))
          .catch((e: Error) => setErr(e.message))}>📁 Lưu về thư mục…</button>
        <span className={dir ? "ok-text" : "muted"}>{dir ? `📂 ${dir.name} (tự lưu theo phòng/máy)` :
          "Chưa chọn — bài vẫn nằm trên máy chủ 7 ngày, tải tay ở bảng dưới"}</span>
      </div>
      {!limited && (
        <div className="wk-pick">
          <label className="check"><input type="checkbox" checked={thu} onChange={(e) => setThu(e.target.checked)} />
            💾 Lưu trên máy chủ (cấu trúc THU/&lt;Ca&gt;/&lt;Phòng&gt;/&lt;Máy&gt;)</label>
          {thu && (
            <select value={ca} onChange={(e) => setCa(e.target.value)} aria-label="Ca thi">
              <option value="">Ca: tự theo giờ</option>
              <option value="Ca sáng">Ca sáng</option>
              <option value="Ca chiều">Ca chiều</option>
            </select>
          )}
        </div>
      )}
      <label className="check"><input type="checkbox" checked={del} onChange={(e) => {
        setDel(e.target.checked);
        setConfirmDel(false);
      }} />
        🗑️ Xoá tệp gốc trên máy trạm sau khi nộp thành công (vĩnh viễn, không vào Thùng rác)</label>
      {confirmDel && (
        <p className="error">Sẽ XOÁ VĨNH VIỄN tệp gốc trên các máy của {what} sau khi nộp. Nên chọn "Lưu về thư mục"
          hoặc "Lưu trên máy chủ" trước. Bấm lần nữa để xác nhận.</p>
      )}
      {err && <p className="error">{err}</p>}
      <div className="actions">
        <button className={confirmDel ? "danger" : ""} onClick={() => void go()} disabled={busy || !src.trim() || !ready}>
          {busy ? "Đang phát lệnh…" : confirmDel ? "Xác nhận thu và XOÁ nguồn" : "Bắt đầu thu bài"}
        </button>
      </div>
      {run && (
        <div className="ctl-res">
          <p>{st ? <>Đã nộp <b>{st.submitted}</b> / {st.total} máy · {st.ca}{!st.complete &&
            ` · chờ tối đa ${st.deadline_s} giây`}</> : "Đã gửi lệnh thu…"}</p>
          <table className="grid wk-res">
            <thead><tr><th>Máy</th><th>Phòng</th><th>Trạng thái</th><th>Lưu</th><th /></tr></thead>
            <tbody>
              {(st?.results ?? []).map((r) => (
                <tr key={r.hostname}>
                  <td>{r.hostname}</td>
                  <td className="muted">{r.room_name}</td>
                  <td><span className={`wk-badge ${BADGE[r.status]}`}>{statusText(r)}</span>
                    {r.status === "ok" && r.deleted && <small className="danger-text"> · đã xoá gốc</small>}</td>
                  <td className="small">
                    {local[r.hostname] && <div className={local[r.hostname].startsWith("lỗi") ? "danger-text" : ""}>
                      💾 {local[r.hostname]}</div>}
                    {r.saved_dir && <div className="muted">THU/{r.saved_dir}</div>}
                    {r.saved_error && <div className="danger-text">THU lỗi: {r.saved_error}</div>}
                  </td>
                  <td>{r.has_zip && (
                    <button className="ghost small" onClick={() => void download(W.zipOnePath(sid, r.hostname),
                      `${r.hostname}.zip`)}>Tải .zip</button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {reasons(run.skipped)}
          <div className="actions">
            <button className="ghost" onClick={() => setLog(true)} disabled={!st}>Nhật ký thu</button>
            <button onClick={() => void download(W.zipAllPath(sid), `BaiThu_${(st?.ca ?? run.ca).replace(/\s+/g, "_")}_${sid.slice(0, 8)}.zip`)}
                    disabled={!st?.submitted}>Tải tất cả (.zip)</button>
          </div>
        </div>
      )}
      {log && st && (
        <CollectLog title="Kết quả thu bài" subtitle={`${what} · ${st.ca} · nguồn ${st.src}`} rows={st.results}
                    local={local} onClose={() => setLog(false)} />
      )}
    </div>
  );
}

// ====================================================================== TỆP ĐÃ GIAO
const TAG: Record<W.Pushed["status"], [string, string]> = {
  pushed: ["accent-text", "📤 đã đẩy"], pending: ["warn-text", "⏳ chờ xoá"], deleted: ["ok-text", "✅ đã xoá"],
};

function PushedTab({ active, roomIds, roomIdsOfDevices, roomNames }: {
  active: boolean; roomIds: string[]; roomIdsOfDevices: string[]; roomNames: string[];
}) {
  const q = useQuery({ queryKey: ["work-pushed"], queryFn: W.pushedList, enabled: active,
    refetchInterval: active ? 3000 : false });
  const [confirm, setConfirm] = useState(false);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const ids = roomIds.length ? roomIds : roomIdsOfDevices;
  const names = new Set(roomNames);
  const items = (q.data?.items ?? []).filter((i) => !names.size || names.has(i.room_name));
  const groups = new Map<string, W.Pushed[]>();
  for (const i of items) groups.set(`${i.room_name}||${i.hostname}`, [...(groups.get(`${i.room_name}||${i.hostname}`) ?? []), i]);
  const live = items.filter((i) => i.status !== "deleted").length;

  async function del() {
    if (!confirm) return setConfirm(true);
    setBusy(true);
    setConfirm(false);
    try {
      setMsg((await W.deletePushed(ids)).message);
      void q.refetch();
    } catch (e) {
      setMsg("❌ " + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wk-pane">
      <p className="muted small">Chỉ ghi nhận tệp máy trạm BÁO đã ghi thật (tệp "đã có, bỏ qua" không bao giờ bị xoá nhầm).
        {names.size ? ` Đang xem: ${[...names].join(", ")}.` : " Đang xem mọi phòng trong phạm vi."}</p>
      {q.isError && <p className="error">{q.error.message}</p>}
      {!q.isPending && !groups.size && <p className="muted">Chưa có tệp nào được ghi nhận.</p>}
      <div className="wk-log">
        {[...groups.entries()].sort(([a], [b]) => a.localeCompare(b, "vi", { numeric: true })).map(([k, fs]) => (
          <div key={k} className="node">
            <div className="host">{fs[0].online ? "🟢" : "🔴"} <b>{fs[0].hostname}</b> <span className="muted">({fs[0].room_name})</span></div>
            {fs.map((f) => (
              <div key={f.folder + f.filename} className="line">
                {f.filename} <span className={TAG[f.status][0]}>{TAG[f.status][1]}</span>
                <div className="muted small">📁 {f.folder}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
      {msg && <p className="notice">{msg}</p>}
      {confirm && <p className="error">XOÁ VĨNH VIỄN {live} tệp đã giao (không vào Thùng rác)? Máy đang tắt sẽ được xoá
        khi online lại. Bấm lần nữa để xác nhận.</p>}
      <div className="actions">
        <button className="danger" onClick={() => void del()} disabled={busy || !live}>
          {busy ? "Đang xoá…" : confirm ? "Xác nhận xoá" : `Xoá ${live} tệp đã giao`}
        </button>
      </div>
    </div>
  );
}
