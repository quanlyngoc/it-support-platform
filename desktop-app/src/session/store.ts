// Trạng thái phiên: địa chỉ Core, mã tổ chức gần nhất (nhớ cho lần sau — đặc tả §10), token Bearer, người dùng.
import { create } from "zustand";
import { readValue, writeValue } from "./storage";
import type { SessionInfo } from "../api-client/types";

export const DEFAULT_BASE_URL = "http://127.0.0.1:7009";

type State = {
  ready: boolean;
  baseUrl: string;
  tenantCode: string;
  token: string | null;
  session: SessionInfo | null;
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
  hydrate: async () => {
    const [baseUrl, tenantCode, token, session] = await Promise.all([
      readValue<string>("baseUrl"),
      readValue<string>("tenantCode"),
      readValue<string>("token"),
      readValue<SessionInfo>("session"),
    ]);
    set({
      ready: true,
      baseUrl: baseUrl || DEFAULT_BASE_URL,
      tenantCode: tenantCode || "",
      token: token || null,
      session: session || null,
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
    set({ tenantCode, token, session });
  },
  logout: () => {
    void writeValue("token", undefined);
    void writeValue("session", undefined);
    set({ token: null, session: null }); // giữ mã tổ chức + địa chỉ máy chủ cho lần đăng nhập sau
  },
}));
