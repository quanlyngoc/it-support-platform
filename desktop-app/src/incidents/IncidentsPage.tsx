// Trang Sự cố (Sổ tay 8.2) — thay /admin + /incident_logs + /export_incidents + log máy trạm + cấu hình email/Telegram
// của hệ cũ. Danh sách lọc theo trạng thái / nguồn / từ khoá / khoảng ngày (Core lọc, cùng bộ lọc cho xuất Excel); bấm
// một dòng → hộp thoại xử lý. Realtime `incident_update` / `incident_new` làm mới danh sách (Layout đã nghe sẵn).
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { Incident, ListResult } from "../api-client/types";
import { fmtTime } from "../shared/metrics";
import { useCan } from "../shared/perm";
import {
  download, filterQuery, saveAlerts, stamp, testAlerts, TRANG_THAI,
  type AlertCfg, type AlertSave, type ClientLog, type IncidentFilter,
} from "./api";
import { IncidentDialog } from "./IncidentDialog";

type Tab = "list" | "logs" | "alerts";

export function IncidentsPage() {
  const canHandle = useCan("incident.handle");
  const canConfig = useCan("system.configure");
  const [tab, setTab] = useState<Tab>("list");
  return (
    <section>
      <div className="dash-head">
        <h1>Sự cố</h1>
        {(canHandle || canConfig) && (
          <div className="seg">
            <button className={tab === "list" ? "on" : ""} onClick={() => setTab("list")}>Danh sách</button>
            {canHandle && <button className={tab === "logs" ? "on" : ""} onClick={() => setTab("logs")}>Log máy trạm</button>}
            {canConfig && (
              <button className={tab === "alerts" ? "on" : ""} onClick={() => setTab("alerts")}>Kênh cảnh báo</button>
            )}
          </div>
        )}
      </div>
      {tab === "list" && <IncidentList />}
      {tab === "logs" && canHandle && <ClientLogs />}
      {tab === "alerts" && canConfig && <AlertSettings />}
    </section>
  );
}

function IncidentList() {
  const canExport = useCan("report.export");
  const [f, setF] = useState<IncidentFilter>({ status: "OPEN" });
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const filt = { ...f, q: q.trim() || undefined };
  const qs = filterQuery(filt);
  const list = useQuery({
    queryKey: ["incidents", "page", qs],
    queryFn: () => getJson<ListResult<Incident>>(`/api/incidents?limit=1000&${qs}`),
    refetchInterval: 60000,
  });
  const set = (k: keyof IncidentFilter) => (e: { target: { value: string } }) =>
    setF((o) => ({ ...o, [k]: e.target.value || undefined }));

  return (
    <>
      <div className="toolbar filters">
        <select value={f.status ?? ""} onChange={set("status")} aria-label="Trạng thái">
          <option value="OPEN">Đang mở</option>
          <option value="PENDING">Chờ xử lý</option>
          <option value="PROCESSING">Đang xử lý</option>
          <option value="DONE">Đã xong</option>
          <option value="">Tất cả trạng thái</option>
        </select>
        <select value={f.source ?? ""} onChange={set("source")} aria-label="Nguồn">
          <option value="">Mọi nguồn</option>
          <option value="USER">Người báo hỏng</option>
          <option value="SYSTEM_WATCHDOG">Hệ thống (phần cứng)</option>
        </select>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm máy, phòng, mô tả, người…"
               maxLength={64} />
        <label className="small">Từ <input type="date" value={f.date_from ?? ""} onChange={set("date_from")} /></label>
        <label className="small">đến <input type="date" value={f.date_to ?? ""} onChange={set("date_to")} /></label>
        <span className="muted small">{list.data ? `${list.data.total} sự cố` : ""}</span>
        {canExport && (
          <button className="ghost" onClick={() => {
            setErr("");
            download(`/api/incidents/export?${qs}`, `Bao_Cao_Su_Co_${stamp()}.xlsx`).catch((e: Error) => setErr(e.message));
          }}>Xuất Excel</button>
        )}
      </div>
      {err && <p className="error">{err}</p>}
      {list.isPending && <p className="muted">Đang tải…</p>}
      {list.isError && <p className="error">{list.error.message}</p>}
      {list.data && (list.data.items.length === 0 ? <p className="muted">Không có sự cố nào khớp bộ lọc.</p> : (
        <table className="grid inc-table">
          <thead>
            <tr><th>Thời gian</th><th>Phòng</th><th>Máy</th><th>Người báo</th><th>Mô tả lỗi</th><th>IT xử lý</th>
              <th>Nội dung xử lý</th><th>Trạng thái</th></tr>
          </thead>
          <tbody>
            {list.data.items.map((i) => (
              <tr key={i.id} className={`click${i.source !== "USER" ? " sys" : ""}`} onClick={() => setOpen(i.id)}>
                <td>{fmtTime(i.created_at)}</td>
                <td>{i.room_name}</td>
                <td><b>{i.hostname}</b></td>
                <td>{i.source === "USER" ? i.reporter_name : <span className="badge warn">HỆ THỐNG</span>}</td>
                <td>
                  {i.items?.length ? i.items.map((it) => (
                    <div key={it.n} className={it.done ? "ok-text" : "err-text"}>{it.done ? "✓" : "•"} {it.n}. {it.text}</div>
                  )) : <span className="err-text">{i.description || i.title}</span>}
                </td>
                <td>{i.resolver_name}</td>
                <td className="small">{i.it_notes?.map((n, k) => <div key={k}>{n.text}</div>)}</td>
                <td><span className={`st st-${i.status}`}>{TRANG_THAI[i.status]}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
      {open && <IncidentDialog id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function ClientLogs() {
  const [host, setHost] = useState("");
  const [q, setQ] = useState("");
  const p = new URLSearchParams({ limit: "300" });
  if (host.trim()) p.set("hostname", host.trim());
  if (q.trim()) p.set("q", q.trim());
  const logs = useQuery({
    queryKey: ["client-logs", p.toString()],
    queryFn: () => getJson<ListResult<ClientLog>>(`/api/client-logs?${p.toString()}`),
    refetchInterval: 30000,
  });
  return (
    <>
      <p className="muted small">Lỗi agent máy trạm tự gửi về (cập nhật, truyền tệp…) — giữ 90 ngày.</p>
      <div className="toolbar filters">
        <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="Đúng tên máy" maxLength={64} />
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm trong ngữ cảnh / lỗi"
               maxLength={64} />
      </div>
      {logs.isPending && <p className="muted">Đang tải…</p>}
      {logs.isError && <p className="error">{logs.error.message}</p>}
      {logs.data && (logs.data.items.length === 0 ? <p className="muted">Chưa có log nào.</p> : (
        <table className="grid">
          <thead><tr><th>Thời gian</th><th>Máy</th><th>IP</th><th>Ngữ cảnh</th><th>Lỗi</th></tr></thead>
          <tbody>
            {logs.data.items.map((l) => (
              <tr key={l.id}>
                <td>{fmtTime(l.created_at)}</td><td><b>{l.hostname}</b></td><td>{l.ip}</td><td>{l.context}</td>
                <td className="log-err" title={l.error}>{l.error}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </>
  );
}

const TEXT: [keyof AlertSave, string, string][] = [
  ["telegram_chat_id", "Telegram — chat ID", "-100…"],
  ["smtp_server", "Máy chủ SMTP", "smtp.gmail.com"],
  ["smtp_port", "Cổng SMTP", "587 (465 = SSL)"],
  ["sender_email", "Email gửi", "it@…"],
];

function AlertSettings() {
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["alert-cfg"], queryFn: () => getJson<AlertCfg>("/api/settings/alerts") });
  if (cfg.isPending) return <p className="muted">Đang tải…</p>;
  if (cfg.isError) return <p className="error">{cfg.error.message}</p>;
  return <AlertForm cfg={cfg.data} onSaved={(c) => qc.setQueryData(["alert-cfg"], c)} />;
}

function AlertForm({ cfg, onSaved }: { cfg: AlertCfg; onSaved: (c: AlertCfg) => void }) {
  const [form, setForm] = useState<AlertSave>({
    smtp_server: cfg.smtp_server, smtp_port: cfg.smtp_port, sender_email: cfg.sender_email,
    receiver_email: cfg.receiver_email, telegram_chat_id: cfg.telegram_chat_id, gmail_app_password: "",
    telegram_bot_token: "",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const put = (k: keyof AlertSave, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));

  async function act(fn: () => Promise<{ ok: boolean; text: string }>) {
    setBusy(true);
    setMsg(null);
    try {
      setMsg(await fn());
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const save = () => act(async () => {
    const c = await saveAlerts(form);
    onSaved(c);
    setForm((f) => ({ ...f, gmail_app_password: "", telegram_bot_token: "", clear_gmail_app_password: false,
      clear_telegram_bot_token: false }));
    return { ok: true, text: "Đã lưu cấu hình kênh cảnh báo." };
  });
  const test = (ch: "email" | "telegram") => act(async () => {
    const r = await testAlerts(ch, form);
    return { ok: r.ok, text: r.message };
  });

  return (
    <div className="alert-form">
      <p className="muted small">
        Phiếu báo hỏng mới và sự cố phần cứng tự phát hiện được gửi Telegram (ngay) rồi email. Để trống kênh nào thì bỏ
        qua kênh đó. Mật khẩu / token đã lưu không hiện lại — để trống là giữ nguyên.
      </p>
      <p className="small">
        Telegram: <b className={cfg.telegram_ready ? "ok-text" : "err-text"}>{cfg.telegram_ready ? "sẵn sàng" : "chưa đủ"}</b>
        {" · "}Email: <b className={cfg.email_ready ? "ok-text" : "err-text"}>{cfg.email_ready ? "sẵn sàng" : "chưa đủ"}</b>
      </p>
      <div className="form-grid">
        <label>Telegram — token bot
          <input type="password" value={form.telegram_bot_token ?? ""} autoComplete="off"
                 onChange={(e) => put("telegram_bot_token", e.target.value)}
                 placeholder={cfg.has_telegram_bot_token ? `đã lưu (${cfg.telegram_bot_token_mask})` : "123456:ABC…"} />
        </label>
        {cfg.has_telegram_bot_token && (
          <label className="small chk"><input type="checkbox" checked={!!form.clear_telegram_bot_token}
                                             onChange={(e) => put("clear_telegram_bot_token", e.target.checked)} />
            Xoá token đã lưu</label>
        )}
        {TEXT.map(([k, label, ph]) => (
          <label key={k}>{label}
            <input value={String(form[k] ?? "")} placeholder={ph} onChange={(e) => put(k, e.target.value)} />
          </label>
        ))}
        <label>Mật khẩu ứng dụng (Gmail App Password)
          <input type="password" value={form.gmail_app_password ?? ""} autoComplete="off"
                 onChange={(e) => put("gmail_app_password", e.target.value)}
                 placeholder={cfg.has_gmail_app_password ? `đã lưu (${cfg.gmail_app_password_mask})` : ""} />
        </label>
        {cfg.has_gmail_app_password && (
          <label className="small chk"><input type="checkbox" checked={!!form.clear_gmail_app_password}
                                             onChange={(e) => put("clear_gmail_app_password", e.target.checked)} />
            Xoá mật khẩu đã lưu</label>
        )}
        <label className="wide">Email nhận (nhiều địa chỉ: phẩy hoặc xuống dòng)
          <textarea rows={3} value={form.receiver_email ?? ""} onChange={(e) => put("receiver_email", e.target.value)} />
        </label>
      </div>
      <div className="actions">
        <button className="ghost" disabled={busy} onClick={() => void test("telegram")}>Gửi thử Telegram</button>
        <button className="ghost" disabled={busy} onClick={() => void test("email")}>Gửi thử email</button>
        <button disabled={busy} onClick={() => void save()}>{busy ? "Đang xử lý…" : "Lưu"}</button>
      </div>
      {msg && <p className={msg.ok ? "notice" : "error"} role="status">{msg.text}</p>}
    </div>
  );
}
