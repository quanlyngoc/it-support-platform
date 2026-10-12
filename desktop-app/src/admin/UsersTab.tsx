// Tab Người dùng (Sổ tay 8.3) — thay bảng tài khoản Local + AD ở Settings hệ cũ. Một bảng chung (cột Loại), lọc nhanh,
// tạo / sửa trong hộp thoại, khoá / mở bằng nút gạt, xoá bấm 2 lần. Dòng của chính mình: không khoá / xoá / đổi policy
// (Core cũng chặn); tài khoản Super Admin với người không phải Super Admin: khoá dòng, hiện "Quản trị viên".
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { ListResult } from "../api-client/types";
import { fmtTime } from "../shared/metrics";
import { useCan } from "../shared/perm";
import { Modal, Toggle } from "../shared/ui";
import { send, type AdminUser, type Policy } from "./api";

export function UsersTab() {
  const qc = useQueryClient();
  const canToggle = useCan("user.toggle");
  const canEdit = useCan("user.edit");
  const canDelete = useCan("user.delete");
  const canNewLocal = useCan("local_user.create");
  const canNewAd = useCan("ad_user.add");
  const canDelLocal = useCan("local_user.delete");
  const canDelAd = useCan("ad_user.delete");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [edit, setEdit] = useState<AdminUser | "LOCAL" | "AD" | null>(null);
  const [armed, setArmed] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => getJson<ListResult<AdminUser>>("/api/admin/users") });
  const reload = () => void qc.invalidateQueries({ queryKey: ["admin"] });

  async function act(fn: () => Promise<unknown>) {
    setErr("");
    try {
      await fn();
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const f = q.trim().toLowerCase();
  const rows = (users.data?.items ?? []).filter((u) => (!kind || u.user_type === kind) &&
    (!f || [u.username, u.display_name, u.email, u.policies.join(" ")].some((x) => x.toLowerCase().includes(f))));

  return (
    <>
      <div className="toolbar filters">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm tài khoản, tên, email, policy…" />
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Loại tài khoản">
          <option value="">Local + AD</option><option value="LOCAL">Chỉ Local</option><option value="AD">Chỉ AD</option>
        </select>
        <span className="muted small">{users.data ? `${rows.length} tài khoản` : ""}</span>
        {canNewLocal && <button onClick={() => setEdit("LOCAL")}>＋ Tài khoản Local</button>}
        {canNewAd && <button className="ghost" onClick={() => setEdit("AD")}>＋ Đăng ký tài khoản AD</button>}
      </div>
      {err && <p className="error">{err}</p>}
      {users.isPending && <p className="muted">Đang tải…</p>}
      {users.isError && <p className="error">{users.error.message}</p>}
      {users.data && (
        <table className="grid">
          <thead>
            <tr><th>Tài khoản</th><th>Loại</th><th>Policy</th><th>Email</th><th>Giới hạn IP</th><th>Đăng nhập cuối</th>
              <th>Sử dụng</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((u) => {
              const canDel = (canDelete || (u.user_type === "LOCAL" ? canDelLocal : canDelAd)) && !u.is_self && !u.locked;
              return (
                <tr key={u.id} className={u.is_active ? "" : "off"}>
                  <td><b>{u.username}</b>{u.is_self && <span className="badge">bạn</span>}
                    {u.display_name && u.display_name !== u.username && <div className="muted small">{u.display_name}</div>}</td>
                  <td><span className={`badge${u.user_type === "AD" ? " gv" : ""}`}>{u.user_type}</span></td>
                  <td>{u.policies.length ? u.policies.join(", ") : <span className="muted">—</span>}
                    {u.is_super && <span className="badge warn">Super Admin</span>}</td>
                  <td className="small">{u.email}</td>
                  <td className="small">{u.allowed_ip_cidrs.length
                    ? <span className="ip-dot red" title="Chỉ đăng nhập từ các IP này">{u.allowed_ip_cidrs.join("; ")}</span>
                    : <span className="ip-dot green">Mọi nơi</span>}</td>
                  <td className="small">{fmtTime(u.last_login_at) || "—"}</td>
                  <td>
                    <Toggle checked={u.is_active} disabled={!canToggle || u.is_self || u.locked}
                            onChange={(v) => void act(() => send("POST", `/api/admin/users/${u.id}/active`, { is_active: v }))} />
                  </td>
                  <td className="row-actions">
                    {canEdit && !u.locked && <button className="ghost small" onClick={() => setEdit(u)}>Sửa</button>}
                    {canDel && (
                      <button className={`ghost small danger-text${armed === u.id ? " armed" : ""}`}
                              onClick={() => {
                                if (armed !== u.id) {
                                  setArmed(u.id);
                                  setTimeout(() => setArmed((a) => (a === u.id ? null : a)), 4000);
                                  return;
                                }
                                setArmed(null);
                                void act(() => send("DELETE", `/api/admin/users/${u.id}`));
                              }}>{armed === u.id ? "Bấm lần nữa để xoá" : "Xoá"}</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {edit && <UserDialog user={typeof edit === "string" ? null : edit} kind={typeof edit === "string" ? edit : edit.user_type}
                           onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
}

function UserDialog({ user, kind, onClose, onDone }: {
  user: AdminUser | null; kind: "LOCAL" | "AD"; onClose: () => void; onDone: () => void;
}) {
  const pols = useQuery({ queryKey: ["admin", "policies"], queryFn: () => getJson<ListResult<Policy>>("/api/admin/policies") });
  const [username, setUsername] = useState(user?.username ?? "");
  const [display, setDisplay] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [phone, setPhone] = useState(user?.phone ?? "");
  const [password, setPassword] = useState("");
  const [pids, setPids] = useState<string[]>(user?.policy_ids ?? []);
  const [ipOn, setIpOn] = useState((user?.allowed_ip_cidrs.length ?? 0) > 0);
  const [ips, setIps] = useState((user?.allowed_ip_cidrs ?? []).join("; "));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const self = !!user?.is_self;

  async function save() {
    if (ipOn && !ips.trim()) {
      setErr("Bật giới hạn IP thì phải nhập ít nhất một IP / dải IP.");
      return;
    }
    setBusy(true);
    setErr("");
    const cidrs = ipOn ? ips.split(/[;,\s]+/).map((x) => x.trim()).filter(Boolean) : [];
    try {
      if (user) {
        await send("PUT", `/api/admin/users/${user.id}`, {
          display_name: display, email, phone, password: password || null,
          ...(self ? {} : { policy_ids: pids, allowed_ip_cidrs: cidrs }),
        });
      } else {
        await send("POST", "/api/admin/users", { user_type: kind, username, display_name: display, email, phone,
          password, policy_ids: pids, allowed_ip_cidrs: cidrs });
      }
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const title = user ? `Sửa tài khoản ${user.username}` : kind === "AD" ? "Đăng ký tài khoản AD" : "Tạo tài khoản Local";
  return (
    <Modal title={title} onClose={onClose} busy={busy}>
      <div className="form-grid one">
        {!user && (
          <label>Tên đăng nhập
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus
                   placeholder={kind === "AD" ? "vd. anh.nguyen (tự thêm @domain của LDAP)" : "vd. it01"} />
          </label>
        )}
        <label>Tên hiển thị<input value={display} onChange={(e) => setDisplay(e.target.value)} /></label>
        <label><span>Email <small className="muted">(dùng để ghép tài khoản khi đăng nhập SSO)</small></span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" />
        </label>
        <label>Điện thoại<input value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
        {(kind === "LOCAL") && (
          <label>{user ? "Đặt mật khẩu mới (để trống = giữ nguyên)" : "Mật khẩu (≥ 6 ký tự)"}
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </label>
        )}
        <fieldset className="pol-pick" disabled={self}>
          <legend>Policy {self && <small className="muted">(không tự đổi policy của chính mình)</small>}</legend>
          {pols.data?.items.map((p) => (
            <label key={p.id} className="chk">
              <input type="checkbox" checked={pids.includes(p.id)}
                     onChange={(e) => setPids((s) => e.target.checked ? [...s, p.id] : s.filter((x) => x !== p.id))} />
              {p.name}{p.rooms.length > 0 && <small className="muted"> · {p.rooms.length} phòng</small>}
            </label>
          ))}
          {pols.data && pols.data.items.length === 0 && <span className="muted small">Chưa có policy nào.</span>}
        </fieldset>
        <div className="ip-row">
          <Toggle checked={ipOn} disabled={self} onChange={setIpOn}
                  label={ipOn ? "Chỉ đăng nhập từ IP / dải IP đã gán" : "Đăng nhập mọi nơi"} />
          {ipOn && <input value={ips} disabled={self} onChange={(e) => setIps(e.target.value)}
                          placeholder="vd. 10.21.24.0/24; 192.168.1.10" />}
        </div>
        {user && <p className="muted small">Đổi policy có hiệu lực từ lần đăng nhập sau của người đó (giống hệ cũ). Đặt lại
          mật khẩu → mọi phiên đang mở của tài khoản bị đăng xuất.</p>}
      </div>
      {err && <p className="error" role="alert">{err}</p>}
      <div className="actions">
        <button className="ghost" onClick={onClose} disabled={busy}>Huỷ</button>
        <button onClick={() => void save()} disabled={busy || (!user && !username.trim())}>{busy ? "Đang lưu…" : "Lưu"}</button>
      </div>
    </Modal>
  );
}
