// Đăng nhập (đặc tả §10): Tài khoản + Mật khẩu + các nút đăng nhập — KHÔNG câu giải thích (yêu cầu người dùng 12/10/2026).
// Mã tổ chức (nhớ lần trước, mặc định PHENIKAA) + địa chỉ máy chủ nằm trong nút ⚙ thu gọn; tự mở khi sai mã tổ chức.
// Ô TOTP chỉ hiện khi máy chủ yêu cầu.
// SSO (Sổ tay 8.3): gõ mã tổ chức → hỏi Core cơ chế đang bật (`/api/auth/methods`) → có SSO thì hiện nút "Đăng nhập bằng
// <nhà cung cấp>": Core cấp auth_url → mở bằng TRÌNH DUYỆT của máy (người dùng đăng nhập + MFA ở nhà cung cấp) → ứng dụng
// hỏi lại Core mỗi 1,5 s tới khi có token (không cần đăng ký đường dẫn riêng cho ứng dụng).
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";
import { openUrl } from "@tauri-apps/plugin-opener";
import { api, errorMessage } from "../api-client";
import type { ApiError, LoginResponse, SessionInfo } from "../api-client/types";
import { loginMethods, ssoPoll, ssoStart, type LoginMethods } from "../admin/api";
import { IN_TAURI } from "../shared/platform";
import { useSession } from "../session/store";

const POLL_MS = 1500;
const DEFAULT_TENANT = (import.meta.env.VITE_DEFAULT_TENANT as string | undefined) || "PHENIKAA";

export function LoginPage() {
  const { token, baseUrl, tenantCode, setServer, login } = useSession();
  const navigate = useNavigate();
  const [server, setServerInput] = useState(baseUrl);
  const [tenant, setTenant] = useState(tenantCode || DEFAULT_TENANT);
  const [conn, setConn] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [methods, setMethods] = useState<LoginMethods | null>(null);
  const [sso, setSso] = useState<{ url: string } | null>(null);
  const cancel = useRef(false);

  useEffect(() => {
    // hỏi cơ chế đăng nhập khi mã tổ chức / máy chủ đổi (đợi gõ xong 400 ms)
    const t = tenant.trim();
    if (t.length < 2) {
      setMethods(null);
      return;
    }
    let live = true;
    const h = setTimeout(() => {
      void loginMethods(server, t).then((m) => live && setMethods(m));
    }, 400);
    return () => {
      live = false;
      clearTimeout(h);
    };
  }, [tenant, server]);

  useEffect(() => () => {
    cancel.current = true;
  }, []);

  if (token) return <Navigate to="/" replace />;

  function done(tc: string, tok: string, session: SessionInfo) {
    login(tc, tok, session);
    navigate("/", { replace: true });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setServer(server);
    try {
      const { data, error: err, response } = await api().POST("/api/auth/login", {
        body: { tenant_code: tenant.trim(), username: username.trim(), password, totp: needTotp ? totp.trim() : null },
      });
      if (response.ok && data) {
        const r = data as unknown as LoginResponse;
        done(r.session.tenant_code, r.token, r.session);
        return;
      }
      const ae = err as ApiError | undefined;
      if (ae?.code === "TOTP_REQUIRED") {
        setNeedTotp(true);
      } else {
        if (ae?.code === "TENANT") setConn(true);
        setError(errorMessage(ae, `Đăng nhập không thành công (${response.status})`));
      }
    } catch (ex) {
      setError(errorMessage(ex));
    } finally {
      setBusy(false);
    }
  }

  async function openBrowser(url: string) {
    if (IN_TAURI) await openUrl(url);
    else window.open(url, "_blank", "noopener");
  }

  async function startSso() {
    setError("");
    setServer(server);
    cancel.current = false;
    const tc = tenant.trim();
    // Chạy trong trình duyệt (pnpm dev): mở cửa sổ NGAY lúc bấm — mở sau một lệnh chờ mạng là bị chặn popup.
    // Bản cài (Tauri) mở trình duyệt hệ thống bằng plugin opener, không vướng chặn popup.
    const pre = IN_TAURI ? null : window.open("about:blank", "_blank");
    try {
      const st = await ssoStart(server, tc);
      setSso({ url: st.auth_url });
      if (pre) pre.location.href = st.auth_url;
      else await openBrowser(st.auth_url);
      const end = Date.now() + st.expires_in * 1000;
      while (!cancel.current && Date.now() < end) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        if (cancel.current) break;
        let p;
        try {
          p = await ssoPoll(server, tc, st.login_id);
        } catch {
          continue; // mạng chập chờn — hỏi lại nhịp sau
        }
        if (p.status === "done") {
          done(p.session.tenant_code, p.token, p.session);
          return;
        }
        if (p.status !== "pending") {
          setError(p.message);
          break;
        }
      }
      if (!cancel.current && Date.now() >= end) setError("Quá thời gian chờ đăng nhập SSO — bấm lại nút đăng nhập.");
    } catch (ex) {
      pre?.close();
      setError(errorMessage(ex, "Không bắt đầu được đăng nhập SSO"));
    } finally {
      setSso(null);
    }
  }

  if (sso) {
    return (
      <main className="login">
        <div className="login-card">
          <h1>Phenikaa IT Monitor</h1>
          <p className="sso-wait">Đang chờ đăng nhập {methods?.sso_label ?? "SSO"} trên trình duyệt…</p>
          <button type="button" className="ghost" onClick={() => void openBrowser(sso.url)}>Mở lại trang đăng nhập</button>
          <button type="button" className="ghost" onClick={() => { cancel.current = true; setSso(null); }}>Huỷ</button>
        </div>
      </main>
    );
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={submit}>
        <h1>Phenikaa IT Monitor</h1>
        <label>
          Tài khoản
          <input name="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus
                 autoComplete="username" />
        </label>
        <label>
          Mật khẩu
          <input name="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                 autoComplete="current-password" />
        </label>
        {needTotp && (
          <label>
            Mã TOTP (6 số)
            <input value={totp} onChange={(e) => setTotp(e.target.value)} inputMode="numeric" maxLength={10}
                   required autoFocus />
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Đang đăng nhập…" : "Đăng nhập"}</button>
        {methods?.sso && (
          <>
            <div className="or" />
            <button type="button" className="ghost sso-btn" onClick={() => void startSso()} disabled={busy}>
              Đăng nhập bằng {methods.sso_label || "SSO"}
            </button>
          </>
        )}
        <details className="server" open={conn} onToggle={(e) => setConn((e.target as HTMLDetailsElement).open)}>
          <summary title="Mã tổ chức và địa chỉ máy chủ" aria-label="Kết nối">⚙</summary>
          <label>
            Mã tổ chức
            <input name="tenant" value={tenant} onChange={(e) => setTenant(e.target.value)} required
                   autoCapitalize="characters" />
          </label>
          <label>
            Máy chủ
            <input name="server" value={server} onChange={(e) => setServerInput(e.target.value)} />
          </label>
        </details>
      </form>
    </main>
  );
}
