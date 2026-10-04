// PowerShell hàng loạt (Sổ tay 6.4): chạy quyền SYSTEM trên các máy đã chọn / cả phòng, kết quả TỪNG máy.
// Bài học 18b ("treo ⏳ mãi" dù máy đã chạy xong): KHÔNG chỉ dựa vào sự kiện realtime — vừa nghe `ps_bulk_result`
// (vào room kết quả ngay khi có token) vừa POLL Core mỗi 3 s; Core tự đánh dấu "Hết giờ" khi quá hạn (timeout + 45 s).
import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, getJson } from "../api-client";
import { realtime, request } from "../realtime-client";
import { Modal } from "../shared/ui";
import type { ControlTarget } from "./ControlDialog";

type Row = { hostname: string; status: string; exit_code?: number | null; stdout?: string; stderr?: string };
type Status = { token: string; total: number; finished: number; complete: boolean; elapsed_s: number;
  deadline_s: number; results: Row[] };
type Started = { token: string; total: number; skipped: { hostname?: string; id?: string; reason: string }[] };

const MAU = [
  { t: "Tên máy + người chạy", s: "hostname; whoami" },
  { t: "Dung lượng ổ đĩa", s: "Get-PSDrive -PSProvider FileSystem | Select Name,@{n='TrongGB';e={[math]::Round($_.Free/1GB,1)}}" },
  { t: "Phiên bản Windows", s: "(Get-CimInstance Win32_OperatingSystem).Caption + ' ' + (Get-CimInstance Win32_OperatingSystem).Version" },
];

const NHAN: Record<string, string> = { running: "Đang chạy…", done: "Xong", success: "Xong", error: "Lỗi",
  failed: "Lỗi", timeout: "Hết giờ" };

export function BulkPsDialog({ target, onClose }: { target: ControlTarget; onClose: () => void }) {
  const [script, setScript] = useState("hostname; whoami");
  const [timeout, setTimeoutS] = useState(90);
  const [exGv, setExGv] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [run, setRun] = useState<Started | null>(null);
  const [st, setSt] = useState<Status | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const what = target.kind === "room" ? `cả ${target.name}` : target.names.length === 1 ? target.names[0]
    : `${target.names.length} máy đã chọn`;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const scope = target.kind === "room"
      ? { room_id: target.roomId, device_ids: [] as string[], exclude_gv: exGv }
      : { room_id: null, device_ids: target.ids, exclude_gv: true };
    const r = await api().POST("/api/terminal/bulk", { body: { ...scope, script, timeout } });
    setBusy(false);
    if (!r.response.ok) return setError(errorMessage(r.error));
    setRun(r.data as unknown as Started);
  }

  // Có token → nghe kết quả realtime + poll 3 s tới khi xong
  useEffect(() => {
    if (!run) return;
    const tok = run.token;
    let stop = false;
    const poll = async () => {
      try {
        const s = await getJson<Status>(`/api/terminal/bulk/${tok}`);
        if (!stop) setSt(s);
        return s.complete;
      } catch {
        return false;
      }
    };
    void request("subscribe_result", { token: tok });
    const sock = realtime();
    const on = (p: { token: string }) => {
      if (p?.token === tok) void poll(); // có kết quả mới → lấy lại bảng ĐẦY ĐỦ (không tự ghép tay)
    };
    sock?.on("ps_bulk_result", on);
    void poll();
    const t = window.setInterval(() => void poll().then((done) => done && window.clearInterval(t)), 3000);
    return () => {
      stop = true;
      window.clearInterval(t);
      sock?.off("ps_bulk_result", on);
    };
  }, [run]);

  return (
    <Modal title={`PowerShell hàng loạt — ${what}`} onClose={onClose} busy={busy} wide>
      {!run ? (
        <form className="form bulk-ps" onSubmit={submit}>
          <label>Script PowerShell (chạy quyền SYSTEM trên từng máy)
            <textarea className="mono" rows={7} value={script} onChange={(e) => setScript(e.target.value)} autoFocus />
          </label>
          <div className="toolbar">
            <span className="muted small">Mẫu:</span>
            {MAU.map((m) => <button key={m.t} type="button" className="ghost small" onClick={() => setScript(m.s)}>{m.t}</button>)}
          </div>
          <label>Thời gian chờ mỗi máy
            <select value={timeout} onChange={(e) => setTimeoutS(Number(e.target.value))}>
              {[30, 60, 90, 180, 300, 600].map((s) => <option key={s} value={s}>{s} giây</option>)}
            </select>
          </label>
          {target.kind === "room" && (
            <label className="check"><input type="checkbox" checked={exGv} onChange={(e) => setExGv(e.target.checked)} />
              Chừa máy giảng viên</label>
          )}
          {error && <p className="error">{error}</p>}
          <div className="actions">
            <button type="button" className="ghost" onClick={onClose} disabled={busy}>Huỷ</button>
            <button type="submit" disabled={busy || !script.trim()}>{busy ? "Đang gửi…" : "Chạy"}</button>
          </div>
        </form>
      ) : (
        <div className="ctl-res">
          <p>
            {st ? <>Đã báo <b>{st.finished}</b> / {st.total} máy{!st.complete && ` · tối đa ${st.deadline_s} giây`}</>
              : `Đã gửi tới ${run.total} máy…`}
          </p>
          <table className="grid bulk-res">
            <thead><tr><th>Máy</th><th>Kết quả</th><th>Đầu ra</th></tr></thead>
            <tbody>
              {(st?.results ?? []).map((r) => (
                <tr key={r.hostname} className={open === r.hostname ? "sel" : ""}
                    onClick={() => setOpen(open === r.hostname ? null : r.hostname)}>
                  <td>{r.hostname}</td>
                  <td className={r.status === "running" ? "muted" : ["done", "success"].includes(r.status) && !r.exit_code
                    ? "ok-text" : "danger-text"}>
                    {NHAN[r.status] ?? r.status}{r.exit_code ? ` (mã ${r.exit_code})` : ""}
                  </td>
                  <td>
                    {open === r.hostname
                      ? <pre className="mono">{[r.stdout, r.stderr].filter(Boolean).join("\n") || "(trống)"}</pre>
                      : <span className="muted small">{(r.stdout || r.stderr || "").split("\n")[0].slice(0, 80)}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {run.skipped.length > 0 && (
            <details>
              <summary>Bỏ qua {run.skipped.length} máy</summary>
              <ul className="small">{run.skipped.map((s, i) => <li key={i}>{s.hostname ?? s.id} — {s.reason}</li>)}</ul>
            </details>
          )}
          <div className="actions"><button onClick={onClose}>Đóng</button></div>
        </div>
      )}
    </Modal>
  );
}
