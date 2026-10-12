// Gọi API Quản trị nền tảng (Sổ tay 8.3) + đăng nhập SSO. Core kiểm quyền ở MỌI API; Desktop chỉ ẩn/hiện cho gọn.
import { authFetch, jsonOf } from "../api-client";
import type { SessionInfo } from "../api-client/types";

export type AdminUser = {
  id: string; username: string; display_name: string; user_type: "LOCAL" | "AD"; email: string; phone: string;
  upn: string; is_active: boolean; totp_enabled: boolean; allowed_ip_cidrs: string[]; policy_ids: string[];
  policies: string[]; is_super: boolean; locked: boolean; is_self: boolean; last_login_at: string | null;
  created_at: string | null;
};

export type Perm = { code: string; name: string; group: string };

export type Policy = {
  id: string; name: string; description: string; system: boolean; users: number; permissions: string[];
  room_ids: string[]; rooms: string[];
};

export type OnlineSession = {
  id: string; username: string; user_kind: string; method: string; ip: string; created_at: string | null;
  last_seen_at: string | null; is_me: boolean; is_super: boolean;
};

export type AuditRow = {
  id: string; created_at: string | null; system: string; actor: string; action: string; detail: string; ip: string;
  status: number | null;
};

export type LdapCfg = {
  enabled: boolean; server: string; domain: string; base_dn: string; bind_user: string; has_bind_pass: boolean;
  bind_pass_mask: string;
};
export type SsoCfg = {
  enabled: boolean; provider_name: string; issuer: string; client_id: string; scopes: string; username_claim: string;
  allowed_domains: string; redirect_uri: string; has_client_secret: boolean; client_secret_mask: string;
  effective_redirect_uri: string;
};
export type AuthCfg = { local: { enabled: true }; ldap: LdapCfg; sso: SsoCfg };

export type SystemInfo = {
  version: string; host: string; port: number; mongo_db: string; data_dir: string; session_ttl_hours: number;
  trusted_proxies: string[]; allowed_origins: string; legacy_tenant_code: string; legacy_allowed_cidrs: string[];
  vnc_relay: string; dev_master_key: boolean; sso_redirect_default: string;
};

export async function send<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  return jsonOf<T>(await authFetch(path, {
    method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }));
}

export type LoginMethods = { local: boolean; ldap: boolean; sso: boolean; sso_label: string };

/** Màn đăng nhập (chưa có token): cơ chế đang bật của tổ chức. */
export async function loginMethods(server: string, tenant: string): Promise<LoginMethods | null> {
  try {
    const r = await fetch(`${server.replace(/\/+$/, "")}/api/auth/methods?tenant_code=${encodeURIComponent(tenant)}`);
    return r.ok ? ((await r.json()) as LoginMethods) : null;
  } catch {
    return null;
  }
}

async function pub<T>(server: string, path: string, body: unknown): Promise<T> {
  const r = await fetch(`${server.replace(/\/+$/, "")}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return jsonOf<T>(r);
}

export type SsoStart = { login_id: string; auth_url: string; expires_in: number };
export type SsoPoll =
  | { status: "pending" }
  | { status: "error" | "expired"; message: string }
  | { status: "done"; token: string; expires_at: string; user: { username: string }; session: SessionInfo };

export const ssoStart = (server: string, tenant: string) =>
  pub<SsoStart>(server, "/api/auth/sso/start", { tenant_code: tenant });
export const ssoPoll = (server: string, tenant: string, loginId: string) =>
  pub<SsoPoll>(server, "/api/auth/sso/poll", { tenant_code: tenant, login_id: loginId });
