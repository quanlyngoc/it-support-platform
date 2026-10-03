// Ẩn/hiện nút theo quyền của phiên. Chỉ để giao diện gọn — Core vẫn kiểm quyền ở MỌI API (không tin Desktop).
import { useSession } from "../session/store";

export function useCan(code: string): boolean {
  return useSession((s) => !!s.session && (s.session.is_super || s.session.permissions.includes(code)));
}
