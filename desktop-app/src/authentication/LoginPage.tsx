// Đăng nhập (đặc tả §10): Mã tổ chức (nhớ lần trước) + Tài khoản + Mật khẩu; ô TOTP chỉ hiện khi máy chủ yêu cầu.
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";
import { api, errorMessage } from "../api-client";
import type { ApiError, LoginResponse } from "../api-client/types";
import { useSession } from "../session/store";

export function LoginPage() {
  const { token, baseUrl, tenantCode, setServer, login } = useSession();
  const navigate = useNavigate();
  const [server, setServerInput] = useState(baseUrl);
  const [tenant, setTenant] = useState(tenantCode);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (token) return <Navigate to="/" replace />;

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
        login(r.session.tenant_code, r.token, r.session);
        navigate("/", { replace: true });
        return;
      }
      const ae = err as ApiError | undefined;
      if (ae?.code === "TOTP_REQUIRED") {
        setNeedTotp(true);
        setError("Tài khoản này cần mã xác thực 2 lớp (TOTP).");
      } else {
        setError(errorMessage(ae, `Đăng nhập không thành công (${response.status})`));
      }
    } catch (ex) {
      setError(errorMessage(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={submit}>
        <h1>Phenikaa IT Monitor</h1>
        <p className="muted">Đăng nhập bằng mã tổ chức và tài khoản được cấp.</p>
        <label>
          Mã tổ chức
          <input value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="VD: PHENIKAA" required
                 autoFocus={!tenant} autoCapitalize="characters" />
        </label>
        <label>
          Tài khoản
          <input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus={!!tenant}
                 autoComplete="username" />
        </label>
        <label>
          Mật khẩu
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                 autoComplete="current-password" />
        </label>
        {needTotp && (
          <label>
            Mã TOTP (6 số)
            <input value={totp} onChange={(e) => setTotp(e.target.value)} inputMode="numeric" maxLength={10}
                   required autoFocus />
          </label>
        )}
        <details className="server">
          <summary>Máy chủ: {server}</summary>
          <input value={server} onChange={(e) => setServerInput(e.target.value)} aria-label="Địa chỉ máy chủ" />
        </details>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Đang đăng nhập…" : "Đăng nhập"}</button>
      </form>
    </main>
  );
}
