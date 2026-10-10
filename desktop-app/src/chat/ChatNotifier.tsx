// Báo tin chat mới (Sổ tay 8.1) — chạy suốt phiên (gắn ở Layout), kể cả khi ngăn chat đóng:
//  - huy hiệu số trên nút "💬 Chat" + tiền tố "(n)" ở tiêu đề cửa sổ (số TUYỆT ĐỐI lấy lại từ Core, không cộng dồn);
//  - tin của NGƯỜI KHÁC tới mà mình không đang xem đúng hội thoại đó → toast trong ứng dụng (bấm mở đúng phòng) + tiếng
//    "ting" + thông báo Windows thật (plugin notification — Windows tự nháy taskbar; chỉ khi cửa sổ không được xem);
//  - đang mở đúng hội thoại và đang nhìn cửa sổ → im lặng (như chatbox.js: không làm phiền khi đang chat).
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { realtime, useRealtime } from "../realtime-client";
import { useSession } from "../session/store";
import { notifyOs, pageActive } from "../shared/notify";
import * as C from "./api";

const BASE_TITLE = document.title;

export function ChatNotifier() {
  const qc = useQueryClient();
  const connected = useRealtime((s) => s.connected);
  const userId = useSession((s) => s.session?.user_id);
  const n = C.useChat((s) => s.unread);

  useEffect(() => {
    document.title = n > 0 ? `(${n > 99 ? "99+" : n}) ${BASE_TITLE}` : BASE_TITLE;
  }, [n]);

  useEffect(() => {
    const refresh = () => void C.unread().then((u) => C.useChat.setState({ unread: u.unread })).catch(() => undefined);
    refresh();
    const t = window.setInterval(refresh, 30000);
    const s = realtime();
    const on = (ev: C.ChatEvent) => {
      if (ev.scope !== C.SCOPE) return;
      void qc.invalidateQueries({ queryKey: ["chat-conv"] });
      if (ev.kind !== "message" || ev.sender_id === userId) return refresh();
      refresh();
      const st = C.useChat.getState();
      if (st.open && st.room === ev.room_id && pageActive()) return; // đang chat đúng phòng này
      C.useChat.setState({ toast: ev });
      C.ding();
      void notifyOs(`💬 ${ev.room_name ?? "Chat"}`, `${ev.sender ?? ""}: ${ev.preview ?? ""}`);
    };
    s?.on("chat_event", on);
    return () => {
      window.clearInterval(t);
      s?.off("chat_event", on);
    };
  }, [connected, userId, qc]);

  return <ChatToast />;
}

function ChatToast() {
  const toast = C.useChat((s) => s.toast);
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => C.useChat.setState({ toast: null }), 4500);
    return () => window.clearTimeout(t);
  }, [toast]);
  if (!toast) return null;
  return (
    <button className="chat-toast" onClick={() => C.openChat(toast.room_id)} title="Mở hội thoại">
      <b>💬 {toast.room_name}</b>
      <span>{toast.sender}: {toast.preview}</span>
    </button>
  );
}

/** Nút trên thanh trên cùng: bật/tắt ngăn chat, huy hiệu số tin chưa đọc. */
export function ChatButton() {
  const n = C.useChat((s) => s.unread);
  const open = C.useChat((s) => s.open);
  return (
    <button className={`ghost chat-btn${open ? " on" : ""}`} onClick={() => C.useChat.setState({ open: !open, toast: null })}
            title="Trò chuyện theo phòng">
      💬 Chat{n > 0 && <span className="chat-badge">{n > 99 ? "99+" : n}</span>}
    </button>
  );
}
