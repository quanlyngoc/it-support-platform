// Hộp thoại sự cố (Sổ tay 8.2) — thay bảng /admin + modal "Xử lý" của hệ cũ:
// - Phiếu người báo: từng dòng lỗi có ô chọn; IT tick các dòng đã sửa + ghi nội dung → dòng đó xong (xanh, khoá lại);
//   mọi dòng xong thì phiếu Xong. "Ghi chú" = nhận xử lý mà chưa chốt dòng nào (→ Đang xử lý).
// - Phiếu hệ thống (RAM / ổ cứng / pin CMOS): xử lý một lần là xong cả phiếu.
// - Ai trong phạm vi phòng cũng bổ sung được dòng mới khi phiếu còn mở (hệ cũ: nút "+" ở thẻ máy).
// Ghi chú / xử lý cần quyền incident.handle (Core kiểm lại). Hai IT cùng thao tác: Core từ chối người sau (409) → tải lại.
import { useEffect, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { Incident } from "../api-client/types";
import { fmtTime } from "../shared/metrics";
import { useCan } from "../shared/perm";
import { Modal } from "../shared/ui";
import { appendIssue, noteIssue, reportIssue, resolveIssue, TRANG_THAI } from "./api";

export function IncidentDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const canHandle = useCan("incident.handle");
  const q = useQuery({ queryKey: ["incidents", "one", id], queryFn: () => getJson<Incident>(`/api/incidents/${id}`) });
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [text, setText] = useState("");
  const [more, setMore] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const inc = q.data;
  const open = inc ? inc.status !== "DONE" : false;
  const items = inc?.items ?? [];
  const isUser = inc?.source === "USER" && items.length > 0;

  useEffect(() => {
    // dữ liệu mới (realtime / người khác vừa xử lý) → bỏ chọn các dòng đã xong
    setSel((s) => new Set([...s].filter((n) => items.some((it) => it.n === n && !it.done))));
  }, [inc]);

  async function run(fn: () => Promise<Incident>, after?: () => void) {
    setBusy(true);
    setErr("");
    try {
      const doc = await fn();
      qc.setQueryData(["incidents", "one", id], doc);
      void qc.invalidateQueries({ queryKey: ["incidents"] });
      after?.();
    } catch (e) {
      setErr((e as Error).message);
      void q.refetch();
    } finally {
      setBusy(false);
    }
  }

  const toggle = (n: number) => setSel((s) => {
    const x = new Set(s);
    if (x.has(n)) x.delete(n);
    else x.add(n);
    return x;
  });

  return (
    <Modal title={inc ? `Sự cố — ${inc.hostname ?? ""}` : "Sự cố"} onClose={onClose} busy={busy} wide>
      {q.isPending && <p className="muted">Đang tải…</p>}
      {q.isError && <p className="error">{q.error.message}</p>}
      {inc && (
        <div className="inc">
          <dl className="kv inc-meta">
            <dt>Phòng</dt><dd>{inc.room_name || "—"}</dd>
            <dt>Người báo</dt>
            <dd>{inc.source === "USER" ? inc.reporter_name : <span className="badge warn">HỆ THỐNG</span>}</dd>
            <dt>Thời điểm</dt><dd>{fmtTime(inc.created_at)}</dd>
            <dt>Trạng thái</dt><dd><span className={`st st-${inc.status}`}>{TRANG_THAI[inc.status]}</span>
              {inc.resolved_at && <span className="muted"> · xong lúc {fmtTime(inc.resolved_at)}</span>}</dd>
            {inc.resolver_name && (<><dt>IT xử lý</dt><dd>{inc.resolver_name}</dd></>)}
          </dl>

          <h3>Mô tả lỗi</h3>
          {isUser ? (
            <ul className="inc-lines">
              {items.map((it) => (
                <li key={it.n} className={it.done ? "done" : ""}>
                  <label>
                    {canHandle && open && (
                      <input type="checkbox" checked={it.done || sel.has(it.n)} disabled={it.done || busy}
                             onChange={() => toggle(it.n)} />
                    )}
                    <span><b>{it.n}.</b> {it.text}</span>
                  </label>
                  <small className="muted">
                    {fmtTime(it.at)} · {it.by}
                    {it.done && <> · ✓ xong {fmtTime(it.done_at)} ({it.done_by})</>}
                  </small>
                </li>
              ))}
            </ul>
          ) : (
            <p className="inc-sys"><b>{inc.title}</b><br />{inc.description}</p>
          )}

          {(inc.it_notes?.length ?? 0) > 0 && (
            <>
              <h3>Nội dung xử lý</h3>
              <ul className="inc-notes">
                {inc.it_notes!.map((nt, i) => (
                  <li key={i}>
                    {nt.lines.length > 0 && <span className="badge">dòng {nt.lines.join(", ")}</span>} {nt.text}
                    <small className="muted"> — {nt.by}, {fmtTime(nt.at)}</small>
                  </li>
                ))}
              </ul>
            </>
          )}

          {open && inc.source === "USER" && (
            <form className="inc-add" onSubmit={(e) => {
              e.preventDefault();
              if (more.trim()) void run(() => appendIssue(id, more), () => setMore(""));
            }}>
              <input value={more} onChange={(e) => setMore(e.target.value)} maxLength={1000} disabled={busy}
                     placeholder="Bổ sung lỗi mới cho máy này…" />
              <button type="submit" className="ghost" disabled={busy || !more.trim()}>Bổ sung</button>
            </form>
          )}

          {open && canHandle && (
            <div className="inc-handle">
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={1000}
                        disabled={busy} placeholder="Nội dung xử lý / ghi chú của IT (bắt buộc)…" />
              <div className="actions">
                <button className="ghost" disabled={busy || !text.trim()} title="Nhận xử lý, chưa chốt dòng nào"
                        onClick={() => void run(() => noteIssue(id, text), () => setText(""))}>Ghi chú</button>
                {isUser && (
                  <button disabled={busy || !text.trim() || sel.size === 0}
                          onClick={() => void run(() => resolveIssue(id, text, [...sel]), () => setText(""))}>
                    Xử lý {sel.size || ""} dòng đã chọn
                  </button>
                )}
                <button className={isUser ? "ghost" : ""} disabled={busy || !text.trim()}
                        onClick={() => void run(() => resolveIssue(id, text, []), () => setText(""))}>
                  Xong cả phiếu
                </button>
              </div>
            </div>
          )}
          {err && <p className="error" role="alert">{err}</p>}
          <div className="actions"><button className="ghost" onClick={onClose} disabled={busy}>Đóng</button></div>
        </div>
      )}
    </Modal>
  );
}

/** "Báo hỏng" một máy (hệ cũ: nút trên thẻ máy). Máy đã có phiếu đang mở → Core bổ sung dòng vào phiếu đó. */
export function ReportDialog({ device, hasOpen, onClose, onDone }: {
  device: { id: string; hostname: string }; hasOpen?: boolean; onClose: () => void; onDone: (msg: string) => void;
}) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setErr("");
    try {
      const r = await reportIssue(device.id, text);
      void qc.invalidateQueries({ queryKey: ["incidents"] });
      onDone(r.appended ? `Đã bổ sung vào phiếu đang mở của ${device.hostname}.`
        : `Đã báo hỏng ${device.hostname} — IT đã được thông báo.`);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Báo hỏng — ${device.hostname}`} onClose={onClose} busy={busy}>
      <form onSubmit={(e) => void submit(e)}>
        {hasOpen && <p className="muted small">Máy đang có phiếu chưa xử lý xong — nội dung sẽ được bổ sung vào phiếu đó.</p>}
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} maxLength={1000} autoFocus
                  disabled={busy} placeholder="Mô tả lỗi (vd. máy không lên mạng, chuột hỏng…)" style={{ width: "100%" }} />
        {err && <p className="error" role="alert">{err}</p>}
        <div className="actions">
          <button type="button" className="ghost" onClick={onClose} disabled={busy}>Huỷ</button>
          <button type="submit" disabled={busy || !text.trim()}>{busy ? "Đang gửi…" : "Gửi"}</button>
        </div>
      </form>
    </Modal>
  );
}
