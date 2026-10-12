// Trang Quản trị nền tảng (Sổ tay 8.3) — thay trang Settings của hệ cũ. Mỗi tab chỉ hiện khi có quyền tương ứng (Core
// vẫn kiểm lại ở mọi API): Người dùng / Phiên (user.view) · Policy (policy.* hoặc user.view) · Đăng nhập + Kênh cảnh báo
// + Hệ thống (system.configure) · Nhật ký (audit.view).
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { ListResult } from "../api-client/types";
import { AlertSettings } from "../incidents/IncidentsPage";
import { fmtTime } from "../shared/metrics";
import { useCan } from "../shared/perm";
import { send, type AuditRow, type OnlineSession, type SystemInfo } from "./api";
import { AgentUpdateTab } from "./AgentUpdateTab";
import { AuthTab } from "./AuthTab";
import { PoliciesTab } from "./PoliciesTab";
import { UsersTab } from "./UsersTab";

type Tab = "users" | "policies" | "sessions" | "auth" | "alerts" | "agent" | "audit" | "system";

export function useAdminVisible(): boolean {
  const a = useCan("user.view");
  const b = useCan("policy.edit");
  const c = useCan("policy.create");
  const d = useCan("system.configure");
  const e = useCan("audit.view");
  const f = useCan("agent.update");
  return a || b || c || d || e || f;
}

export function AdminPage() {
  const canUsers = useCan("user.view");
  const canPolEdit = useCan("policy.edit");
  const canPolNew = useCan("policy.create");
  const canPol = canPolEdit || canPolNew || canUsers;
  const canSys = useCan("system.configure");
  const canAudit = useCan("audit.view");
  const canAgent = useCan("agent.update");
  const tabs: [Tab, string, boolean][] = [
    ["users", "Người dùng", canUsers], ["policies", "Policy", canPol], ["sessions", "Phiên đang mở", canUsers],
    ["auth", "Đăng nhập (LDAP / SSO)", canSys], ["alerts", "Kênh cảnh báo", canSys], ["agent", "Cập nhật Agent", canAgent],
    ["audit", "Nhật ký", canAudit],
    ["system", "Hệ thống", canSys],
  ];
  const shown = tabs.filter((t) => t[2]);
  const [tab, setTab] = useState<Tab | null>(null);
  const cur = tab && shown.some((t) => t[0] === tab) ? tab : shown[0]?.[0];
  if (!cur) return <p className="muted">Tài khoản không có quyền quản trị nào.</p>;
  return (
    <section>
      <div className="dash-head">
        <h1>Quản trị</h1>
        <div className="seg">
          {shown.map(([k, label]) => (
            <button key={k} className={cur === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </div>
      {cur === "users" && <UsersTab />}
      {cur === "policies" && <PoliciesTab />}
      {cur === "sessions" && <SessionsTab />}
      {cur === "auth" && <AuthTab />}
      {cur === "alerts" && <AlertSettings />}
      {cur === "agent" && <AgentUpdateTab />}
      {cur === "audit" && <AuditTab />}
      {cur === "system" && <SystemTab />}
    </section>
  );
}

const CACH: Record<string, string> = { LOCAL: "Local", AD: "LDAP / AD", SSO: "SSO" };

function SessionsTab() {
  const qc = useQueryClient();
  const canKick = useCan("user.toggle");
  const [err, setErr] = useState("");
  const s = useQuery({
    queryKey: ["admin", "sessions"], queryFn: () => getJson<ListResult<OnlineSession>>("/api/admin/sessions"),
    refetchInterval: 30000,
  });
  async function kick(id: string) {
    setErr("");
    try {
      await send("DELETE", `/api/admin/sessions/${id}`);
      void qc.invalidateQueries({ queryKey: ["admin", "sessions"] });
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <>
      <p className="muted small">Phiên còn hạn có hoạt động trong 15 phút gần nhất. "Đăng xuất" có hiệu lực ngay trên máy đó.</p>
      {err && <p className="error">{err}</p>}
      {s.isPending && <p className="muted">Đang tải…</p>}
      {s.isError && <p className="error">{s.error.message}</p>}
      {s.data && (
        <table className="grid">
          <thead><tr><th>Tài khoản</th><th>Đăng nhập bằng</th><th>IP</th><th>Từ lúc</th><th>Hoạt động cuối</th><th /></tr></thead>
          <tbody>
            {s.data.items.map((x) => (
              <tr key={x.id}>
                <td><b>{x.username}</b>{x.is_me && <span className="badge">phiên này</span>}
                  {x.is_super && <span className="badge warn">Super Admin</span>}</td>
                <td>{CACH[x.method] ?? x.method}</td><td>{x.ip}</td><td className="small">{fmtTime(x.created_at)}</td>
                <td className="small">{fmtTime(x.last_seen_at)}</td>
                <td className="row-actions">
                  {canKick && !x.is_me && <button className="ghost small danger-text" onClick={() => void kick(x.id)}>Đăng xuất</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function AuditTab() {
  const [system, setSystem] = useState("");
  const [q, setQ] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const p = new URLSearchParams({ limit: "500" });
  if (system) p.set("system", system);
  if (q.trim()) p.set("q", q.trim());
  if (from) p.set("date_from", from);
  if (to) p.set("date_to", to);
  const a = useQuery({
    queryKey: ["admin", "audit", p.toString()],
    queryFn: () => getJson<ListResult<AuditRow>>(`/api/admin/audit?${p.toString()}`),
  });
  return (
    <>
      <div className="toolbar filters">
        <select value={system} onChange={(e) => setSystem(e.target.value)} aria-label="Hệ">
          <option value="">Mọi hệ</option><option value="LAB">LAB — phòng máy</option><option value="HSK">HSK</option>
          <option value="THI">THI</option>
        </select>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm người, thao tác, chi tiết, IP…" />
        <label className="small">Từ <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="small">đến <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <span className="muted small">{a.data ? `${a.data.total} dòng (tối đa 500, giữ 180 ngày)` : ""}</span>
      </div>
      {a.isPending && <p className="muted">Đang tải…</p>}
      {a.isError && <p className="error">{a.error.message}</p>}
      {a.data && (
        <table className="grid">
          <thead><tr><th>Thời gian</th><th>Hệ</th><th>Người</th><th>Thao tác</th><th>Chi tiết</th><th>IP</th><th>KQ</th></tr></thead>
          <tbody>
            {a.data.items.map((r) => (
              <tr key={r.id}>
                <td className="small">{fmtTime(r.created_at)}</td><td>{r.system}</td><td><b>{r.actor}</b></td>
                <td className={r.action.includes("FAIL") ? "err-text" : ""}>{r.action}</td>
                <td className="small">{r.detail}</td><td className="small">{r.ip}</td>
                <td className={`small${(r.status ?? 200) >= 400 ? " err-text" : ""}`}>{r.status ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function SystemTab() {
  const s = useQuery({ queryKey: ["admin", "system"], queryFn: () => getJson<SystemInfo>("/api/admin/system") });
  if (s.isPending) return <p className="muted">Đang tải…</p>;
  if (s.isError) return <p className="error">{s.error.message}</p>;
  const d = s.data;
  return (
    <>
      <p className="muted small">Chỉ xem. Các giá trị này đặt bằng biến môi trường của dịch vụ PlatformCore (người vận hành sửa
        rồi chạy dich_vu_core.ps1 -Lenh CapNhat).</p>
      {d.dev_master_key && <p className="notice warn-notice">Core đang dùng KHOÁ CHỦ mặc định của giai đoạn dựng thử (mã hoá
        bí mật LDAP / SSO / email / Telegram) — đặt MASTER_KEY_B64 riêng trước khi chạy thật.</p>}
      <dl className="kv">
        <dt>Phiên bản Core</dt><dd>{d.version}</dd>
        <dt>Nghe</dt><dd>{d.host}:{d.port}</dd>
        <dt>CSDL</dt><dd>{d.mongo_db}</dd>
        <dt>Kho tệp</dt><dd>{d.data_dir}</dd>
        <dt>Phiên đăng nhập</dt><dd>{d.session_ttl_hours} giờ</dd>
        <dt>Proxy tin cậy</dt><dd>{d.trusted_proxies.join(", ")}</dd>
        <dt>Nguồn được phép (CORS)</dt><dd>{d.allowed_origins}</dd>
        <dt>Tổ chức gắn agent v2</dt><dd>{d.legacy_tenant_code}</dd>
        <dt>Dải IP agent v2</dt><dd>{d.legacy_allowed_cidrs.length ? d.legacy_allowed_cidrs.join(", ") : "mọi IP (chưa giới hạn)"}</dd>
        <dt>Relay xem màn hình</dt><dd>{d.vnc_relay}</dd>
        <dt>Redirect URI SSO (tự suy)</dt><dd>{d.sso_redirect_default}</dd>
      </dl>
    </>
  );
}
