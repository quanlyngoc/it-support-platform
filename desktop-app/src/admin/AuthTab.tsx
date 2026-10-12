// Tab Đăng nhập (Sổ tay 8.3 + yêu cầu 12/10/2026): cơ chế đăng nhập của tổ chức.
// - Local: luôn bật (Super Admin là tài khoản Local — tắt được là có thể tự khoá mình ra ngoài).
// - LDAP / AD: nút gạt. TẮT = Core không gọi AD; tài khoản AD không đăng nhập bằng mật khẩu (vẫn vào được bằng SSO nếu
//   bật). Cấu hình + nút "Kiểm tra kết nối" (bind tài khoản dịch vụ hoặc tài khoản thử) báo đúng mã lỗi AD như hệ cũ.
// - SSO (OpenID Connect): nút gạt. TẮT = màn đăng nhập không còn nút SSO, Core từ chối mọi đăng nhập SSO.
// Nút gạt LƯU NGAY (không cần bấm Lưu); ô cấu hình lưu bằng nút Lưu của từng thẻ. Bí mật chỉ hiện "đã lưu (****)".
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../api-client";
import { Toggle } from "../shared/ui";
import { send, type AuthCfg, type LdapCfg, type SsoCfg } from "./api";

type Msg = { ok: boolean; text: string } | null;

export function AuthTab() {
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["admin", "auth-config"], queryFn: () => getJson<AuthCfg>("/api/admin/auth-config") });
  if (cfg.isPending) return <p className="muted">Đang tải…</p>;
  if (cfg.isError) return <p className="error">{cfg.error.message}</p>;
  const set = (c: AuthCfg) => qc.setQueryData(["admin", "auth-config"], c);
  const c = cfg.data;
  return (
    <div className="auth-cards">
      <section className="auth-card">
        <header><h3>Tài khoản Local</h3><Toggle checked disabled onChange={() => undefined} label="Luôn bật" /></header>
        <p className="muted small">Tài khoản + mật khẩu lưu trong IT Monitor (Super Admin là tài khoản Local). Không tắt được
          để tránh tự khoá mình ra ngoài.</p>
      </section>
      {!c.ldap.enabled && !c.sso.enabled && (
        <p className="notice warn-notice">LDAP và SSO đều đang tắt — chỉ tài khoản Local đăng nhập được.</p>
      )}
      <LdapCard cfg={c.ldap} onSaved={set} />
      <SsoCard cfg={c.sso} onSaved={set} />
    </div>
  );
}

function useAct() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  async function act(fn: () => Promise<Msg>) {
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
  return { busy, msg, act };
}

function Field({ label, value, onChange, ph, type = "text", hint }: {
  label: string; value: string; onChange: (v: string) => void; ph?: string; type?: string; hint?: string;
}) {
  return (
    <label><span>{label}{hint && <small className="muted"> {hint}</small>}</span>
      <input type={type} value={value} placeholder={ph} autoComplete="off" onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function LdapCard({ cfg, onSaved }: { cfg: LdapCfg; onSaved: (c: AuthCfg) => void }) {
  const [f, setF] = useState({ server: cfg.server, domain: cfg.domain, base_dn: cfg.base_dn, bind_user: cfg.bind_user,
    bind_pass: "" });
  const [clear, setClear] = useState(false);
  const [tu, setTu] = useState("");
  const [tp, setTp] = useState("");
  const { busy, msg, act } = useAct();
  const put = (k: keyof typeof f) => (v: string) => setF((o) => ({ ...o, [k]: v }));

  const toggle = (v: boolean) => act(async () => {
    onSaved(await send<AuthCfg>("PUT", "/api/admin/auth-config/ldap", { enabled: v }));
    return { ok: true, text: v ? "Đã BẬT đăng nhập LDAP." : "Đã TẮT đăng nhập LDAP." };
  });
  const save = () => act(async () => {
    onSaved(await send<AuthCfg>("PUT", "/api/admin/auth-config/ldap", { ...f, bind_pass: f.bind_pass || null,
      clear_bind_pass: clear }));
    setF((o) => ({ ...o, bind_pass: "" }));
    setClear(false);
    return { ok: true, text: "Đã lưu cấu hình LDAP." };
  });
  const test = () => act(async () => {
    const r = await send<{ ok: boolean; message: string }>("POST", "/api/admin/auth-config/ldap/test", {
      ...f, bind_pass: f.bind_pass || null, test_user: tu || null, test_password: tp || null });
    return { ok: r.ok, text: r.message };
  });

  return (
    <section className={`auth-card${cfg.enabled ? " on" : ""}`}>
      <header>
        <h3>LDAP / Active Directory</h3>
        <Toggle checked={cfg.enabled} disabled={busy} onChange={(v) => void toggle(v)} label={cfg.enabled ? "Đang bật" : "Đang tắt"} />
      </header>
      <p className="muted small">
        {cfg.enabled ? "Tài khoản AD đã đăng ký đăng nhập bằng mật khẩu AD (Core bind tới máy chủ AD)."
          : "Tài khoản AD KHÔNG đăng nhập bằng mật khẩu được — chỉ vào bằng SSO (nếu SSO bật). Core không gọi AD."}
      </p>
      <div className="form-grid">
        <Field label="Máy chủ" value={f.server} onChange={put("server")} ph="ldaps://10.x.x.x:636 hoặc ldap://10.x.x.x:389" />
        <Field label="Domain" value={f.domain} onChange={put("domain")} ph="phenikaamec.local" hint="(tự ghép khi gõ tên ngắn)" />
        <Field label="Base DN" value={f.base_dn} onChange={put("base_dn")} ph="DC=phenikaamec,DC=local" />
        <Field label="Tài khoản dịch vụ (bind user)" value={f.bind_user} onChange={put("bind_user")} ph="svc_itmonitor@phenikaamec.local" />
        <label>Mật khẩu bind
          <input type="password" value={f.bind_pass} autoComplete="new-password" onChange={(e) => put("bind_pass")(e.target.value)}
                 placeholder={cfg.has_bind_pass ? `đã lưu (${cfg.bind_pass_mask})` : ""} />
        </label>
        {cfg.has_bind_pass && (
          <label className="chk"><input type="checkbox" checked={clear} onChange={(e) => setClear(e.target.checked)} />
            Xoá mật khẩu bind đã lưu</label>
        )}
      </div>
      <details className="auth-test">
        <summary>Thử bằng một tài khoản AD cụ thể (không lưu)</summary>
        <div className="form-grid">
          <Field label="Tài khoản thử" value={tu} onChange={setTu} ph="anh.nguyen" />
          <Field label="Mật khẩu" value={tp} onChange={setTp} type="password" />
        </div>
      </details>
      <div className="actions">
        <button className="ghost" disabled={busy} onClick={() => void test()}>Kiểm tra kết nối</button>
        <button disabled={busy} onClick={() => void save()}>{busy ? "Đang xử lý…" : "Lưu"}</button>
      </div>
      {msg && <p className={msg.ok ? "notice" : "error"} role="status">{msg.text}</p>}
    </section>
  );
}

function SsoCard({ cfg, onSaved }: { cfg: SsoCfg; onSaved: (c: AuthCfg) => void }) {
  const [f, setF] = useState({ provider_name: cfg.provider_name, issuer: cfg.issuer, client_id: cfg.client_id,
    client_secret: "", scopes: cfg.scopes, username_claim: cfg.username_claim, allowed_domains: cfg.allowed_domains,
    redirect_uri: cfg.redirect_uri });
  const [clear, setClear] = useState(false);
  const { busy, msg, act } = useAct();
  const put = (k: keyof typeof f) => (v: string) => setF((o) => ({ ...o, [k]: v }));
  const redirect = f.redirect_uri || cfg.effective_redirect_uri;

  const toggle = (v: boolean) => act(async () => {
    onSaved(await send<AuthCfg>("PUT", "/api/admin/auth-config/sso", { enabled: v }));
    return { ok: true, text: v ? "Đã BẬT đăng nhập SSO — màn đăng nhập hiện nút SSO." : "Đã TẮT đăng nhập SSO." };
  });
  const save = () => act(async () => {
    onSaved(await send<AuthCfg>("PUT", "/api/admin/auth-config/sso", { ...f, client_secret: f.client_secret || null,
      clear_client_secret: clear }));
    setF((o) => ({ ...o, client_secret: "" }));
    setClear(false);
    return { ok: true, text: "Đã lưu cấu hình SSO." };
  });
  const test = () => act(async () => {
    const r = await send<{ ok: boolean; message: string }>("POST", "/api/admin/auth-config/sso/test",
      { issuer: f.issuer, client_id: f.client_id });
    return { ok: r.ok, text: r.message };
  });

  return (
    <section className={`auth-card${cfg.enabled ? " on" : ""}`}>
      <header>
        <h3>SSO — đăng nhập một lần (OpenID Connect)</h3>
        <Toggle checked={cfg.enabled} disabled={busy} onChange={(v) => void toggle(v)} label={cfg.enabled ? "Đang bật" : "Đang tắt"} />
      </header>
      <p className="muted small">
        Người dùng bấm "Đăng nhập bằng {f.provider_name || "SSO"}" → đăng nhập ở trình duyệt (kèm MFA của nhà cung cấp) →
        ứng dụng tự vào. Chỉ tài khoản ĐÃ đăng ký ở tab Người dùng mới vào được (khớp tài khoản AD theo UPN / email / tên trước
        @, tài khoản Local theo email).
      </p>
      <div className="form-grid">
        <Field label="Tên hiện trên nút" value={f.provider_name} onChange={put("provider_name")} ph="Microsoft 365" />
        <Field label="Issuer" value={f.issuer} onChange={put("issuer")}
               ph="https://login.microsoftonline.com/<Directory (tenant) ID>/v2.0" />
        <Field label="Client ID (Application ID)" value={f.client_id} onChange={put("client_id")} />
        <label>Client secret
          <input type="password" value={f.client_secret} autoComplete="new-password"
                 onChange={(e) => put("client_secret")(e.target.value)}
                 placeholder={cfg.has_client_secret ? `đã lưu (${cfg.client_secret_mask})` : "(bỏ trống nếu ứng dụng public + PKCE)"} />
        </label>
        {cfg.has_client_secret && (
          <label className="chk"><input type="checkbox" checked={clear} onChange={(e) => setClear(e.target.checked)} />
            Xoá client secret đã lưu</label>
        )}
        <Field label="Scopes" value={f.scopes} onChange={put("scopes")} ph="openid profile email" />
        <Field label="Claim tên đăng nhập" value={f.username_claim} onChange={put("username_claim")} ph="preferred_username" />
        <Field label="Chỉ cho tên miền" value={f.allowed_domains} onChange={put("allowed_domains")}
               ph="phenikaa-uni.edu.vn (bỏ trống = mọi tên miền)" />
        <Field label="Redirect URI" value={f.redirect_uri} onChange={put("redirect_uri")} ph={cfg.effective_redirect_uri}
               hint="(bỏ trống = tự suy từ địa chỉ máy chủ)" />
      </div>
      <p className="small redirect-box">Đăng ký Redirect URI này ở nhà cung cấp (Microsoft Entra → App registrations →
        Authentication → Web): <code>{redirect}</code>{" "}
        <button className="ghost small" onClick={() => void navigator.clipboard?.writeText(redirect)}>Chép</button></p>
      <div className="actions">
        <button className="ghost" disabled={busy} onClick={() => void test()}>Kiểm tra cấu hình</button>
        <button disabled={busy} onClick={() => void save()}>{busy ? "Đang xử lý…" : "Lưu"}</button>
      </div>
      {msg && <p className={msg.ok ? "notice" : "error"} role="status">{msg.text}</p>}
    </section>
  );
}
