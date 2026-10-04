// Điều khiển từ xa (Sổ tay 6.1–6.3): bật / tắt / khởi động lại, đăng nhập / đăng xuất Windows, ngắt / mở Internet,
// chặn / bỏ chặn website — cho cả phòng, các máy đang chọn, hoặc một máy. Mọi lệnh có hộp xác nhận nêu rõ đích; lệnh
// gây gián đoạn dùng nút đỏ. Core lọc phạm vi phòng + chừa máy GV (cả phòng) và trả về máy nào nhận / bỏ qua vì sao.
import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage } from "../api-client";
import { realtime } from "../realtime-client";
import { Modal } from "../shared/ui";

export type ControlKind = "wake" | "shutdown" | "restart" | "login" | "logout" | "disable" | "enable" | "block_web"
  | "unblock_web";

export const CONTROL_LABEL: Record<ControlKind, string> = {
  wake: "Bật máy", shutdown: "Tắt máy", restart: "Khởi động lại", login: "Đăng nhập Windows…", logout: "Đăng xuất Windows",
  disable: "Ngắt Internet", enable: "Mở Internet", block_web: "Chặn website…", unblock_web: "Bỏ chặn website…",
};
const DANGER: ControlKind[] = ["shutdown", "restart", "logout", "disable"];

export type ControlTarget = { kind: "room"; roomId: string; name: string }
  | { kind: "devices"; ids: string[]; names: string[] };

type Result = {
  sent?: { hostname: string; channel: string }[];
  skipped: { hostname?: string; id?: string; reason: string }[];
  helpers?: { helper: string; subnet: string; count: number }[];
  no_helper?: string[];
  targets?: number;
};
type LoginRes = { hostname: string; status: string; msg?: string };

export function ControlDialog({ kind, target, onClose }: { kind: ControlKind; target: ControlTarget; onClose: () => void }) {
  const [exGv, setExGv] = useState(true);
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [sites, setSites] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [res, setRes] = useState<Result | null>(null);
  const [logins, setLogins] = useState<Record<string, LoginRes>>({});

  // Kết quả đăng nhập từng máy (Core gửi về ĐÚNG người bấm)
  useEffect(() => {
    if (kind !== "login" || !res) return;
    const s = realtime();
    if (!s) return;
    const on = (p: LoginRes) => {
      if (p?.hostname) setLogins((m) => ({ ...m, [p.hostname.toUpperCase()]: p }));
    };
    s.on("login_response", on);
    return () => {
      s.off("login_response", on);
    };
  }, [kind, res]);

  const scope = target.kind === "room" // đủ cả 3 trường: kiểu sinh từ Core coi trường có mặc định là bắt buộc
    ? { room_id: target.roomId, device_ids: [] as string[], exclude_gv: exGv }
    : { room_id: null, device_ids: target.ids, exclude_gv: true };
  const what = target.kind === "room" ? `cả ${target.name}` : target.names.length === 1 ? target.names[0]
    : `${target.names.length} máy đã chọn`;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const c = api();
    const r = kind === "wake" || kind === "shutdown" || kind === "restart"
      ? await c.POST("/api/power", { body: { action: kind, ...scope } })
      : kind === "login" ? await c.POST("/api/remote-login", { body: { ...scope, user: user.trim(), password: pass } })
        : kind === "logout" ? await c.POST("/api/remote-login/logout", { body: scope })
          : await c.POST("/api/internet", { body: { ...scope, action: kind, websites: sites } });
    setBusy(false);
    if (!r.response.ok) return setError(errorMessage(r.error));
    setPass(""); // không giữ mật khẩu trong bộ nhớ giao diện lâu hơn cần
    setRes(r.data as unknown as Result);
  }

  const needSites = kind === "block_web" || kind === "unblock_web";
  return (
    <Modal title={`${CONTROL_LABEL[kind].replace("…", "")} — ${what}`} onClose={onClose} busy={busy}>
      {!res ? (
        <form className="form" onSubmit={submit}>
          {kind === "login" && (
            <>
              <label>Tài khoản Windows<input value={user} onChange={(e) => setUser(e.target.value)} autoFocus
                                              placeholder="vd. SV, THI" autoComplete="off" /></label>
              <label>Mật khẩu<input type="password" value={pass} onChange={(e) => setPass(e.target.value)}
                                     autoComplete="new-password" /></label>
              <p className="muted small">Gửi mã hoá AES-GCM; máy tự kiểm mật khẩu rồi báo kết quả về đây.</p>
            </>
          )}
          {needSites && (
            <label>Website<textarea value={sites} onChange={(e) => setSites(e.target.value)} rows={3} autoFocus
                                     placeholder="facebook.com, youtube.com (mỗi tên miền cách nhau dấu phẩy / xuống dòng)" />
            </label>
          )}
          {kind === "wake" && (
            <p className="muted small">Máy chủ không tới được máy trạm — Core nhờ máy ĐANG BẬT cùng mạng (subnet) bắn
              gói bật máy hộ. Phòng tắt hết thì bật tay một máy rồi bấm lại.</p>
          )}
          {kind === "disable" && (
            <p className="muted small">Chặn trình duyệt + cổng web; kết nối của máy về máy chủ (cổng 5443) KHÔNG bị chặn.</p>
          )}
          {target.kind === "room" && (
            <label className="check"><input type="checkbox" checked={exGv} onChange={(e) => setExGv(e.target.checked)} />
              Chừa máy giảng viên</label>
          )}
          {error && <p className="error">{error}</p>}
          <div className="actions">
            <button type="button" className="ghost" onClick={onClose} disabled={busy}>Huỷ</button>
            <button type="submit" className={DANGER.includes(kind) ? "danger" : ""}
                    disabled={busy || (kind === "login" && !user.trim()) || (needSites && !sites.trim())}>
              {busy ? "Đang gửi…" : CONTROL_LABEL[kind].replace("…", "")}
            </button>
          </div>
        </form>
      ) : (
        <ResultView kind={kind} res={res} logins={logins} onClose={onClose} />
      )}
    </Modal>
  );
}

function ResultView({ kind, res, logins, onClose }: {
  kind: ControlKind; res: Result; logins: Record<string, LoginRes>; onClose: () => void;
}) {
  return (
    <div className="ctl-res">
      {kind === "wake" ? (
        <>
          <p>{res.helpers?.length
            ? `Đã nhờ ${new Set(res.helpers.map((h) => h.helper)).size} máy trung gian bật ${res.targets} máy.`
            : res.targets ? "Không gửi được lệnh bật." : "Không có máy nào cần bật."}</p>
          {!!res.no_helper?.length && (
            <p className="warn-box">Không có máy trung gian cùng mạng đang bật cho: {res.no_helper.join(", ")} — bật tay
              một máy trong phòng đó rồi bấm lại.</p>
          )}
        </>
      ) : (
        <p>Đã gửi tới <b>{res.sent?.length ?? 0}</b> máy.</p>
      )}
      {kind === "login" && !!res.sent?.length && (
        <table className="grid">
          <thead><tr><th>Máy</th><th>Kết quả</th></tr></thead>
          <tbody>
            {res.sent.map((s) => {
              const r = logins[s.hostname.toUpperCase()];
              return (
                <tr key={s.hostname}>
                  <td>{s.hostname}</td>
                  <td className={r ? (r.status === "success" ? "ok-text" : "danger-text") : "muted"}>
                    {r ? (r.status === "success" ? "Đã nhận, đang đăng nhập" : r.msg || r.status) : "Đang chờ máy báo…"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {res.skipped.length > 0 && (
        <details>
          <summary>Bỏ qua {res.skipped.length} máy</summary>
          <ul className="small">
            {res.skipped.map((s, i) => <li key={i}>{s.hostname ?? s.id} — {s.reason}</li>)}
          </ul>
        </details>
      )}
      <div className="actions"><button onClick={onClose} autoFocus>Đóng</button></div>
    </div>
  );
}

/** Ô chọn "Điều khiển…" → mở hộp thoại tương ứng. */
export function ControlMenu({ target, disabled, onPick }: {
  target: ControlTarget; disabled?: boolean; onPick: (k: ControlKind, t: ControlTarget) => void;
}) {
  return (
    <select className="ctl-menu" value="" disabled={disabled} aria-label="Điều khiển"
            onChange={(e) => e.target.value && onPick(e.target.value as ControlKind, target)}>
      <option value="">Điều khiển…</option>
      <optgroup label="Nguồn">
        <option value="wake">{CONTROL_LABEL.wake}</option>
        <option value="shutdown">{CONTROL_LABEL.shutdown}</option>
        <option value="restart">{CONTROL_LABEL.restart}</option>
      </optgroup>
      <optgroup label="Windows">
        <option value="login">{CONTROL_LABEL.login}</option>
        <option value="logout">{CONTROL_LABEL.logout}</option>
      </optgroup>
      <optgroup label="Internet">
        <option value="disable">{CONTROL_LABEL.disable}</option>
        <option value="enable">{CONTROL_LABEL.enable}</option>
        <option value="block_web">{CONTROL_LABEL.block_web}</option>
        <option value="unblock_web">{CONTROL_LABEL.unblock_web}</option>
      </optgroup>
    </select>
  );
}
