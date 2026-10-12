// Tab Policy (Sổ tay 8.3) — thay "Danh sách nhóm Policy (Role)" ở Settings hệ cũ: quyền tick theo nhóm chức năng, phòng
// giới hạn (rỗng = mọi phòng; có phòng = tài khoản phía phòng: chỉ thấy / điều khiển máy của các phòng đó). Policy hệ
// thống (Super Admin) chỉ xem; policy đang gán không xoá được (Core chặn, báo số người).
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { ListResult, Room } from "../api-client/types";
import { useCan } from "../shared/perm";
import { Modal } from "../shared/ui";
import { send, type Perm, type Policy } from "./api";

export function PoliciesTab() {
  const qc = useQueryClient();
  const canCreate = useCan("policy.create");
  const canEdit = useCan("policy.edit");
  const [edit, setEdit] = useState<Policy | "new" | null>(null);
  const [armed, setArmed] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const pols = useQuery({ queryKey: ["admin", "policies"], queryFn: () => getJson<ListResult<Policy>>("/api/admin/policies") });
  const perms = useQuery({ queryKey: ["admin", "perms"], queryFn: () => getJson<{ items: Perm[] }>("/api/admin/permissions") });
  const names = useMemo(() => new Map((perms.data?.items ?? []).map((p) => [p.code, p.name])), [perms.data]);

  async function del(p: Policy) {
    if (armed !== p.id) {
      setArmed(p.id);
      setTimeout(() => setArmed((a) => (a === p.id ? null : a)), 4000);
      return;
    }
    setArmed(null);
    setErr("");
    try {
      await send("DELETE", `/api/admin/policies/${p.id}`);
      void qc.invalidateQueries({ queryKey: ["admin"] });
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <>
      <div className="toolbar filters">
        <span className="muted small">Quyền được chụp vào phiên lúc đăng nhập — sửa policy có hiệu lực từ lần đăng nhập sau.</span>
        {canCreate && <button onClick={() => setEdit("new")}>＋ Tạo policy</button>}
      </div>
      {err && <p className="error">{err}</p>}
      {pols.isPending && <p className="muted">Đang tải…</p>}
      {pols.isError && <p className="error">{pols.error.message}</p>}
      {pols.data && (
        <table className="grid">
          <thead><tr><th>Policy</th><th>Quyền</th><th>Phòng giới hạn</th><th className="num">Người dùng</th><th /></tr></thead>
          <tbody>
            {pols.data.items.map((p) => (
              <tr key={p.id}>
                <td><b>{p.name}</b>{p.system && <span className="badge warn">hệ thống</span>}
                  {p.description && <div className="muted small">{p.description}</div>}</td>
                <td className="small">{p.system ? "Toàn quyền" : p.permissions.map((c) => names.get(c) ?? c).join(", ") || "—"}</td>
                <td className="small">{p.rooms.length ? p.rooms.join(", ") : <span className="muted">Mọi phòng</span>}</td>
                <td className="num">{p.users}</td>
                <td className="row-actions">
                  {(canEdit || p.system) && (
                    <button className="ghost small" onClick={() => setEdit(p)}>{p.system || !canEdit ? "Xem" : "Sửa"}</button>
                  )}
                  {canEdit && !p.system && (
                    <button className={`ghost small danger-text${armed === p.id ? " armed" : ""}`} onClick={() => void del(p)}>
                      {armed === p.id ? "Bấm lần nữa để xoá" : "Xoá"}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {edit && <PolicyDialog policy={edit === "new" ? null : edit} perms={perms.data?.items ?? []}
                             readOnly={edit !== "new" && (edit.system || !canEdit)}
                             onClose={() => setEdit(null)}
                             onDone={() => { setEdit(null); void qc.invalidateQueries({ queryKey: ["admin"] }); }} />}
    </>
  );
}

function PolicyDialog({ policy, perms, readOnly, onClose, onDone }: {
  policy: Policy | null; perms: Perm[]; readOnly: boolean; onClose: () => void; onDone: () => void;
}) {
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => getJson<ListResult<Room>>("/api/rooms") });
  const [name, setName] = useState(policy?.name ?? "");
  const [desc, setDesc] = useState(policy?.description ?? "");
  const [codes, setCodes] = useState<string[]>(policy?.system ? perms.map((p) => p.code) : policy?.permissions ?? []);
  const [rids, setRids] = useState<string[]>(policy?.room_ids ?? []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const groups = useMemo(() => {
    const m = new Map<string, Perm[]>();
    for (const p of perms) m.set(p.group, [...(m.get(p.group) ?? []), p]);
    return [...m.entries()];
  }, [perms]);
  const flip = (list: string[], v: string, on: boolean) => (on ? [...new Set([...list, v])] : list.filter((x) => x !== v));

  async function save() {
    setBusy(true);
    setErr("");
    try {
      const body = { name, description: desc, permissions: codes, room_ids: rids };
      if (policy) await send("PUT", `/api/admin/policies/${policy.id}`, body);
      else await send("POST", "/api/admin/policies", body);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={policy ? (readOnly ? `Policy ${policy.name}` : `Sửa policy ${policy.name}`) : "Tạo policy"}
           onClose={onClose} busy={busy} wide>
      <fieldset disabled={readOnly} className="pol-form">
        <div className="form-grid">
          <label>Tên policy<input value={name} onChange={(e) => setName(e.target.value)} autoFocus={!policy} /></label>
          <label>Mô tả<input value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
        </div>
        <h3>Quyền</h3>
        <div className="perm-groups">
          {groups.map(([g, items]) => (
            <div key={g} className="perm-group">
              <label className="chk grp">
                <input type="checkbox" checked={items.every((p) => codes.includes(p.code))}
                       onChange={(e) => setCodes((s) => items.reduce((acc, p) => flip(acc, p.code, e.target.checked), s))} />
                <b>{g}</b>
              </label>
              {items.map((p) => (
                <label key={p.code} className="chk">
                  <input type="checkbox" checked={codes.includes(p.code)}
                         onChange={(e) => setCodes((s) => flip(s, p.code, e.target.checked))} />
                  {p.name} <small className="muted">{p.code}</small>
                </label>
              ))}
            </div>
          ))}
        </div>
        <h3>Phòng giới hạn <small className="muted">(bỏ trống = mọi phòng; chọn phòng = tài khoản phía phòng, chỉ thấy phòng
          đã chọn)</small></h3>
        <div className="room-pick">
          {(rooms.data?.items ?? []).filter((r) => r.official || rids.includes(r.id)).map((r) => (
            <label key={r.id} className="chk">
              <input type="checkbox" checked={rids.includes(r.id)} onChange={(e) => setRids((s) => flip(s, r.id, e.target.checked))} />
              {r.name}
            </label>
          ))}
        </div>
      </fieldset>
      {err && <p className="error" role="alert">{err}</p>}
      <div className="actions">
        <button className="ghost" onClick={onClose} disabled={busy}>{readOnly ? "Đóng" : "Huỷ"}</button>
        {!readOnly && <button onClick={() => void save()} disabled={busy || !name.trim()}>{busy ? "Đang lưu…" : "Lưu"}</button>}
      </div>
    </Modal>
  );
}
