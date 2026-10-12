// Trạng thái phiên: địa chỉ Core, mã tổ chức gần nhất (nhớ cho lần sau — đặc tả §10), token Bearer, người dùng.
import { create } from "zustand";
import { readValue, writeValue } from "./storage";
import type { SessionInfo } from "../api-client/types";

// Phát triển (pnpm dev / tauri dev): Core chạy cùng máy. Bản cài cho máy quản trị: đi qua Caddy :7443 — chứng chỉ
// hiện cấp cho IP (không phải tên miền) nên địa chỉ mặc định dùng IP. Người dùng đổi được ở ô "Máy chủ" khi đăng nhập.
export const DEFAULT_BASE_URL = import.meta.env.DEV ? "http://127.0.0.1:7009" : "https://10.21.24.142:7443";

type State = {
  ready: boolean;
  baseUrl: string;
  tenantCode: string;
  token: string | null;
  session: SessionInfo | null;
  /** Lần đăng nhập gần nhất trên máy này là Super Admin → màn đăng nhập mới hiện nút ⚙ (mã tổ chức + máy chủ). */
  lastSuper: boolean;
  hydrate: () => Promise<void>;
  setServer: (baseUrl: string) => void;
  login: (tenantCode: string, token: string, session: SessionInfo) => void;
  logout: () => void;
};

export const useSession = create<State>((set) => ({
  ready: false,
  baseUrl: DEFAULT_BASE_URL,
  tenantCode: "",
  token: null,
  session: null,
  lastSuper: false,
  hydrate: async () => {
    const [baseUrl, tenantCode, token, session, lastSuper] = await Promise.all([
      readValue<string>("baseUrl"),
      readValue<string>("tenantCode"),
      readValue<string>("token"),
      readValue<SessionInfo>("session"),
      readValue<boolean>("lastSuper"),
    ]);
    set({
      ready: true,
      baseUrl: baseUrl || DEFAULT_BASE_URL,
      tenantCode: tenantCode || "",
      token: token || null,
      session: session || null,
      lastSuper: !!lastSuper,
    });
  },
  setServer: (baseUrl) => {
    const v = baseUrl.trim().replace(/\/+$/, "");
    void writeValue("baseUrl", v);
    set({ baseUrl: v });
  },
  login: (tenantCode, token, session) => {
    void writeValue("tenantCode", tenantCode);
    void writeValue("token", token);
    void writeValue("session", session);
    void writeValue("lastSuper", session.is_super);
    set({ tenantCode, token, session, lastSuper: session.is_super });
  },
  logout: () => {
    void writeValue("token", undefined);
    void writeValue("session", undefined);
    set({ token: null, session: null }); // giữ mã tổ chức + địa chỉ máy chủ cho lần đăng nhập sau
  },
}));
