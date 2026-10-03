// Client REST gọi Core. Kiểu đường dẫn + thân gửi lên sinh từ OpenAPI của Core (schema.d.ts — `pnpm gen:api`):
// Core đổi API mà Desktop dùng sai thì `pnpm typecheck` báo lỗi đúng chỗ (Sổ tay 4.5).
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";
import type { ApiError } from "./types";
import { useSession } from "../session/store";

const auth: Middleware = {
  onRequest({ request }) {
    const token = useSession.getState().token;
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    // Phiên hết hạn / bị đá (đăng nhập 1 thiết bị) / tài khoản bị khoá → về màn đăng nhập
    if (response.status === 401 && useSession.getState().token) useSession.getState().logout();
    return response;
  },
};

export function api() {
  const c = createClient<paths>({ baseUrl: useSession.getState().baseUrl });
  c.use(auth);
  return c;
}

export function errorMessage(err: unknown, fallback = "Có lỗi khi gọi máy chủ"): string {
  if (err && typeof err === "object" && "message" in err && typeof (err as ApiError).message === "string") {
    return (err as ApiError).message as string;
  }
  if (err instanceof TypeError) return "Không kết nối được máy chủ — kiểm tra địa chỉ máy chủ và mạng";
  return fallback;
}

/** Gọi GET trả dữ liệu đã ép kiểu; lỗi → ném Error với thông báo tiếng Việt của Core. */
export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(useSession.getState().baseUrl + path, {
    headers: { Authorization: `Bearer ${useSession.getState().token ?? ""}` },
  });
  if (res.status === 401) useSession.getState().logout();
  const body = (await res.json().catch(() => ({}))) as unknown;
  if (!res.ok) throw new Error(errorMessage(body, `Lỗi ${res.status}`));
  return body as T;
}
