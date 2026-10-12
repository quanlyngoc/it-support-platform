// Tab Quản trị → Cập nhật Agent (Sổ tay 8.4) — công cụ chính của GĐ10. Luật §0: canary vài máy → 1 phòng → nhiều phòng;
// All Update chỉ bật được khi đã có máy canary chạy đúng bản (Core chặn) + xác nhận ngay trên giao diện; nút DỪNG KHẨN
// luôn ở trên cùng khi cổng đang mở. Đẩy cập nhật = lệnh cài an toàn (updater tách rời, kiểm SHA-256) — xem Core
// `app/legacy_adapter/agent_update.py`. Tiến độ từng máy đọc lại mỗi 5 s khi có đợt đang chạy.
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../api-client";
import { fmtTime } from "../shared/metrics";
import { Toggle } from "../shared/ui";
import { send } from "./api";

type Push = { token: string; at: string; version: string; mode: string; by: string; state: "running" | "done" | "error" | "waiting";
  text: string; updated_at: string | null };
type Machine = { device_id: string; host: string; hostname: string; room_name: string; room_id: string; version: string;
  online: boolean; channel: string; status: "uptodate" | "outdated" | "newer" | "offline" | "unknown"; push: Push | null;
  invited: boolean };
type Gate = { all: boolean; hosts: string[]; rollout_rooms: string[]; rollout_percent: number };
type Status = {
  target: { version: string; sha256: string; size: number } | null; gate: Gate; machines: Machine[]; canary_min: number;
  many: number; push_base: string; can_global: boolean;
  summary: { total: number; online: number; uptodate: number; outdated: number; offline: number; running: number; failed: number };
};
type Release = { version: string; size: number; sha256: string; valid: boolean; problem: string; active: boolean;
  added_at: string | null };
type PushResult = { token: string; version: string; mode: string; sent: string[]; via_http: string[]; no_channel: string[];
  offline: string[]; busy: string[]; skipped_uptodate: string[] };
type Body = { device_ids?: string[]; room_ids?: string[]; version?: string };

const LOC: [string, string][] = [["all", "Tất cả"], ["outdated", "Chưa đúng version"], ["offline", "Offline"],
  ["push", "Đang cài / lỗi"]];
const ST: Record<Machine["status"], string> = { uptodate: "Đúng bản", outdated: "Bản cũ", newer: "Bản mới hơn",
  offline: "Offline", unknown: "—" };

export function AgentUpdateTab() {
  const qc = useQueryClient();
  const s = useQuery({
    queryKey: ["admin", "agent-update"], queryFn: () => getJson<Status>("/api/agent-update/status"),
    refetchInterval: (q) => ((q.state.data?.summary.running ?? 0) > 0 ? 5000 : 30000),
  });
  const rels = useQuery({ queryKey: ["admin", "agent-releases"],
    queryFn: () => getJson<{ items: Release[] }>("/api/agent-update/releases") });
  const [loc, setLoc] = useState("all");
  const [room, setRoom] = useState("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);
  const [word, setWord] = useState("");
  const [many, setMany] = useState<{ body: Body; count: number } | null>(null);
  const [oldVer, setOldVer] = useState("");
  const [armedRel, setArmedRel] = useState("");
  const reload = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "agent-update"] });
    void qc.invalidateQueries({ queryKey: ["admin", "agent-releases"] });
  };

  const d = s.data;
  const roomsList = useMemo(() => {
    const m = new Map<string, string>();
    for (const x of d?.machines ?? []) if (x.room_id) m.set(x.room_id, x.room_name);
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1], "vi", { numeric: true }));
  }, [d]);
  const f = q.trim().toLowerCase();
  const rows = (d?.machines ?? []).filter((m) => (!room || m.room_id === room) && (!f || m.hostname.toLowerCase().includes(f))
    && (loc === "all" || (loc === "outdated" && (m.status === "outdated" || m.status === "newer"))
      || (loc === "offline" && m.status === "offline")
      || (loc === "push" && !!m.push && m.push.state !== "done")));
  const allSel = rows.length > 0 && rows.every((m) => sel.has(m.device_id));
  const gateOpen = !!d && (d.gate.all || d.gate.hosts.length > 0 || d.gate.rollout_rooms.length > 0 || d.gate.rollout_percent > 0);
  const older = (rels.data?.items ?? []).filter((r) => r.valid);

  async function act(fn: () => Promise<{ ok: boolean; text: string } | null>) {
    setBusy(true);
    setMsg(null);
    try {
      setMsg(await fn());
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
      reload();
    }
  }

  async function push(body: Body, confirmMany = false) {
    setMany(null);
    await act(async () => {
      try {
        const r = await send<PushResult>("POST", "/api/agent-update/push", { ...body, confirm_many: confirmMany });
        setSel(new Set());
        const parts = [`Đã gửi lệnh cài bản ${r.version} tới ${r.sent.length} máy`];
        if (r.via_http.length) parts.push(`${r.via_http.length} máy qua kênh HTTP`);
        if (r.skipped_uptodate.length) parts.push(`bỏ qua ${r.skipped_uptodate.length} máy đã đúng bản`);
        if (r.busy.length) parts.push(`${r.busy.length} máy đang cài dở`);
        if (r.offline.length) parts.push(`${r.offline.length} máy đang tắt`);
        if (r.no_channel.length) parts.push(`${r.no_channel.length} máy mất kênh lệnh`);
        return { ok: r.sent.length > 0, text: parts.join(" · ") };
      } catch (e) {
        const m = (e as Error).message;
        const n = /Đợt này (\d+) máy/.exec(m);
        if (n) {
          setMany({ body, count: Number(n[1]) });
          return null;
        }
        throw e;
      }
    });
  }

  if (s.isPending) return <p className="muted">Đang tải…</p>;
  if (s.isError) return <p className="error">{s.error.message}</p>;
  const dd = d!;
  const toggle = (id: string) => setSel((x) => {
    const n = new Set(x);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });

  return (
    <div className="au">
      <section className={`au-head${dd.gate.all ? " live" : ""}`}>
        <div className="au-target">
          <span className="muted small">Bản đang phát</span>
          <b>{dd.target ? dd.target.version : "chưa có"}</b>
          {dd.target && <span className="muted small">{(dd.target.size / 1048576).toFixed(1)} MB · {dd.target.sha256.slice(0, 12)}…</span>}
        </div>
        <div className="au-sum">
          <span><b>{dd.summary.online}</b>/{dd.summary.total} online</span>
          <span className="ok-text"><b>{dd.summary.uptodate}</b> đúng bản</span>
          <span className="warn-text"><b>{dd.summary.outdated}</b> chưa đúng</span>
          <span><b>{dd.summary.offline}</b> offline</span>
          {dd.summary.running > 0 && <span className="accent-text"><b>{dd.summary.running}</b> đang cài</span>}
          {dd.summary.failed > 0 && <span className="err-text"><b>{dd.summary.failed}</b> lỗi</span>}
        </div>
        <div className="au-all">
          <Toggle checked={dd.gate.all} disabled={busy || !dd.can_global || !dd.target}
                  label={dd.gate.all ? "All Update: BẬT" : "All Update: tắt"}
                  onChange={(v) => {
                    if (v) {
                      setConfirmAll(true);
                      setWord("");
                    } else {
                      void act(async () => ({ ok: true, text: (await send<{ message: string }>("PUT", "/api/agent-update/all", { on: false })).message }));
                    }
                  }} />
          {gateOpen && dd.can_global && (
            <button className="danger" disabled={busy}
                    onClick={() => void act(async () => ({ ok: true, text: (await send<{ message: string }>("PUT", "/api/agent-update/all", { on: false })).message }))}>
              ⛔ Dừng khẩn
            </button>
          )}
        </div>
      </section>

      {confirmAll && (
        <div className="au-confirm" role="alertdialog" aria-label="Xác nhận bật All Update">
          <p><b>Bật All Update?</b> Mọi máy online sẽ tự tải và cài bản {dd.target?.version}. Chỉ bật khi đã cập nhật thử
            ≥ {dd.canary_min} máy canary THÀNH CÔNG và chúng đã online lại đúng bản. Theo dõi số máy online suốt đợt — tụt bất
            thường thì bấm Dừng khẩn ngay.</p>
          <div className="au-confirm-row">
            <input value={word} onChange={(e) => setWord(e.target.value)} placeholder="Gõ BẬT để xác nhận" autoFocus />
            <button className="danger" disabled={busy || !["BẬT", "BAT"].includes(word.trim().toUpperCase())}
                    onClick={() => void act(async () => {
                      const r = await send<{ message: string }>("PUT", "/api/agent-update/all", { on: true, confirm: word });
                      setConfirmAll(false);
                      return { ok: true, text: r.message };
                    })}>Bật All Update</button>
            <button className="ghost" onClick={() => setConfirmAll(false)}>Huỷ</button>
          </div>
        </div>
      )}
      {many && (
        <div className="au-confirm" role="alertdialog">
          <p><b>Đợt này {many.count} máy</b> (quá {dd.many}). Canary vài máy → 1 phòng → nhiều phòng — chỉ gửi khi các bước trước đã
            ổn.</p>
          <div className="au-confirm-row">
            <button className="danger" disabled={busy} onClick={() => void push(many.body, true)}>Gửi {many.count} máy</button>
            <button className="ghost" onClick={() => setMany(null)}>Huỷ</button>
          </div>
        </div>
      )}
      {msg && <p className={msg.ok ? "notice" : "error"} role="status">{msg.text}</p>}

      <div className="toolbar filters">
        <div className="seg">
          {LOC.map(([k, label]) => <button key={k} className={loc === k ? "on" : ""} onClick={() => setLoc(k)}>{label}</button>)}
        </div>
        <select value={room} onChange={(e) => setRoom(e.target.value)} aria-label="Phòng">
          <option value="">Mọi phòng</option>
          {roomsList.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm máy…" />
        {room && dd.target && (
          <button className="ghost" disabled={busy} onClick={() => void push({ room_ids: [room] })}>
            Cập nhật cả phòng
          </button>
        )}
        <span className="muted small">{rows.length} máy</span>
      </div>

      {sel.size > 0 && (
        <div className="bulkbar">
          <span>Đã chọn <b>{sel.size}</b> máy</span>
          <button disabled={busy || !dd.target} onClick={() => void push({ device_ids: [...sel] })}>Cập nhật đã chọn</button>
          <select value={oldVer} onChange={(e) => setOldVer(e.target.value)} aria-label="Bản cài lại">
            <option value="">Cài lại bản…</option>
            {older.map((r) => <option key={r.version} value={r.version}>{r.version}{r.active ? " (đang phát)" : ""}</option>)}
          </select>
          <button className="ghost" disabled={busy || !oldVer}
                  onClick={() => void push({ device_ids: [...sel], version: oldVer })}>Cài lại</button>
          <button className="ghost" onClick={() => setSel(new Set())}>Bỏ chọn</button>
        </div>
      )}

      <table className="grid au-table">
        <thead>
          <tr>
            <th className="c-sel"><input type="checkbox" checked={allSel} aria-label="Chọn tất cả"
                                         onChange={() => setSel(allSel ? new Set() : new Set(rows.map((m) => m.device_id)))} /></th>
            <th>Máy</th><th>Phòng</th><th>Phiên bản</th><th>Trạng thái</th><th>Đợt cài gần nhất</th><th />
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.device_id} className={`${m.online ? "" : "off"}${sel.has(m.device_id) ? " sel" : ""}`}>
              <td className="c-sel"><input type="checkbox" checked={sel.has(m.device_id)} onChange={() => toggle(m.device_id)}
                                           aria-label={`Chọn ${m.hostname}`} /></td>
              <td><b>{m.hostname}</b></td>
              <td>{m.room_name}</td>
              <td className={m.status === "uptodate" ? "ok-text" : m.status === "outdated" ? "warn-text" : ""}>{m.version || "—"}</td>
              <td><span className={`dot ${m.online ? "on" : "off"}`} />{ST[m.status]}
                {m.online && m.channel === "http" && <span className="badge" title="Chỉ còn kênh HTTP — lệnh vẫn tới qua hàng đợi">HTTP</span>}</td>
              <td className="small">
                {m.push ? (
                  <span className={`au-st ${m.push.state}`} title={`${m.push.mode === "reinstall" ? "Cài lại" : "Cập nhật"} bản ${m.push.version} — ${m.push.by}`}>
                    {m.push.text} <span className="muted">· {fmtTime(m.push.updated_at ?? m.push.at)}</span>
                  </span>
                ) : <span className="muted">—</span>}
              </td>
              <td>{m.invited && <span className="badge warn" title="Cổng chia đợt đang mời máy này tự lên bản đang phát">được mời</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <details className="au-rel">
        <summary>Kho bản phát hành ({rels.data?.items.length ?? 0})</summary>
        <p className="muted small">Nhập bản mới trên máy chủ: <code>uv run python -m app.legacy_adapter.release_cli nhap</code> (đọc
          thư mục updates của hệ cũ, kiểm SHA-256). Phát hành = đổi bản đang phát; không tự đẩy xuống máy nào.</p>
        <table className="grid">
          <thead><tr><th>Bản</th><th className="num">Dung lượng</th><th>SHA-256</th><th>Nhập lúc</th><th /></tr></thead>
          <tbody>
            {(rels.data?.items ?? []).map((r) => (
              <tr key={r.version}>
                <td><b>{r.version}</b>{r.active && <span className="badge gv">đang phát</span>}
                  {!r.valid && <span className="badge warn" title={r.problem}>hỏng</span>}</td>
                <td className="num">{(r.size / 1048576).toFixed(1)} MB</td>
                <td className="small">{r.sha256.slice(0, 16)}…</td>
                <td className="small">{fmtTime(r.added_at)}</td>
                <td className="row-actions">
                  {dd.can_global && r.valid && !r.active && !dd.gate.all && (
                    <button className={`ghost small${armedRel === r.version ? " armed" : ""}`} disabled={busy}
                            onClick={() => {
                              if (armedRel !== r.version) {
                                setArmedRel(r.version);
                                setTimeout(() => setArmedRel((a) => (a === r.version ? "" : a)), 4000);
                                return;
                              }
                              setArmedRel("");
                              void act(async () => {
                                await send("POST", `/api/agent-update/releases/${r.version}/activate`);
                                return { ok: true, text: `Bản đang phát: ${r.version} — chưa máy nào tự cập nhật.` };
                              });
                            }}>{armedRel === r.version ? "Bấm lần nữa để phát hành" : "Phát hành bản này"}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
