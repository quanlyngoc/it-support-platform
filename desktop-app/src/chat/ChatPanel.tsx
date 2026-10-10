// Ngăn chat (Sổ tay 8.1) — mang hành vi đã tinh chỉnh của chatbox.js hệ cũ: danh sách hội thoại (chưa đọc lên đầu, bong
// bóng số từng phòng), admin chủ động mở chat với BẤT KỲ phòng (kể cả chưa nhắn), ô nhập tự cao tới 120 px (Enter gửi,
// Shift+Enter xuống dòng), DÁN ảnh → nén JPEG → xem trước (× bỏ) → gửi; bấm ảnh phóng to (Esc đóng); cảm xúc; admin xoá
// nội dung / xoá hội thoại. Mở hội thoại khi cửa sổ đang được xem = đánh dấu đã đọc (`active`).
import { useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type KeyboardEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { ListResult, Room } from "../api-client/types";
import { realtime } from "../realtime-client";
import { pageActive } from "../shared/notify";
import * as C from "./api";

const EMOJI = ["👍", "❤️", "😂", "😮", "😢", "🙏"];

export function ChatPanel() {
  const open = C.useChat((s) => s.open);
  if (!open) return null;
  return <ChatInner />;
}

function ChatInner() {
  const qc = useQueryClient();
  const room = C.useChat((s) => s.room);
  const meQ = useQuery({ queryKey: ["chat-me"], queryFn: C.me });
  const convQ = useQuery({ queryKey: ["chat-conv"], queryFn: C.conversations, refetchInterval: 15000 });
  const admin = meQ.data?.side === "admin";
  const roomsQ = useQuery({ queryKey: ["rooms"], queryFn: () => getJson<ListResult<Room>>("/api/rooms"), enabled: admin });
  const convs = convQ.data?.items ?? [];

  useEffect(() => { // phía phòng chỉ có 1 phòng → mở luôn
    if (!room && meQ.data?.side === "room" && meQ.data.rooms.length === 1) C.openChat(meQ.data.rooms[0].id);
  }, [room, meQ.data]);

  const known = new Set(convs.map((c) => c.room_id));
  const picker = (roomsQ.data?.items ?? []).filter((r) => r.official && !known.has(r.id));
  const current = convs.find((c) => c.room_id === room);
  const roomName = current?.room_name ?? roomsQ.data?.items.find((r) => r.id === room)?.name ??
    meQ.data?.rooms.find((r) => r.id === room)?.name ?? "";

  return (
    <aside className="chat-panel" aria-label="Chat">
      <div className="chat-list">
        <div className="chat-list-hd">
          <b>💬 Trò chuyện</b>
          <button className="ghost small" onClick={() => C.useChat.setState({ open: false })} title="Đóng">✕</button>
        </div>
        {admin && (
          <select className="chat-pick" value="" aria-label="Mở chat với phòng"
                  onChange={(e) => e.target.value && C.openChat(e.target.value)}>
            <option value="">＋ Mở chat với phòng…</option>
            {picker.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        )}
        <div className="chat-convs">
          {convQ.isPending && <p className="muted small">Đang tải…</p>}
          {!convQ.isPending && !convs.length && <p className="muted small">Chưa có hội thoại nào.</p>}
          {convs.map((c) => (
            <button key={c.room_id} className={`chat-conv${c.room_id === room ? " on" : ""}${c.unread ? " unread" : ""}`}
                    onClick={() => C.openChat(c.room_id)}>
              <span className="nm">{c.room_name}</span>
              {c.unread > 0 && <span className="ub">{c.unread > 99 ? "99+" : c.unread}</span>}
              <span className="lt">{c.last_admin && c.last ? "Bạn: " : ""}{c.last || "—"}</span>
            </button>
          ))}
        </div>
      </div>
      {room ? (
        <ChatThread key={room} roomId={room} roomName={roomName} admin={admin}
                    onRead={() => {
                      void qc.invalidateQueries({ queryKey: ["chat-conv"] });
                      void C.unread().then((u) => C.useChat.setState({ unread: u.unread })).catch(() => undefined);
                    }} />
      ) : (
        <div className="chat-thread empty"><p className="muted">Chọn một hội thoại để bắt đầu.</p></div>
      )}
    </aside>
  );
}

function dayOf(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("vi-VN", { weekday: "long", day: "2-digit", month: "2-digit" }) : "";
}
function timeOf(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }) : "";
}

function ChatThread({ roomId, roomName, admin, onRead }: {
  roomId: string; roomName: string; admin: boolean; onRead: () => void;
}) {
  const [msgs, setMsgs] = useState<C.Msg[]>([]);
  const [reacts, setReacts] = useState<C.Reacts>({});
  const [err, setErr] = useState("");
  const [text, setText] = useState("");
  const [img, setImg] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [zoom, setZoom] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"" | "keep" | "drop">("");
  const lastId = useRef<string | null>(null);
  const token = useRef<string>("");
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const inp = useRef<HTMLTextAreaElement>(null);

  async function load(full: boolean) {
    try {
      const active = pageActive();
      const t = await C.thread(roomId, full ? null : lastId.current, active);
      if (!full && token.current && t.clear_token !== token.current) return void load(true); // admin vừa xoá → tải lại
      token.current = t.clear_token;
      setReacts(t.reactions);
      if (full) setMsgs(t.messages);
      else if (t.messages.length) setMsgs((m) => [...m, ...t.messages.filter((x) => !m.some((y) => y.id === x.id))]);
      if (t.messages.length) lastId.current = t.messages[t.messages.length - 1].id;
      else if (full) lastId.current = null;
      setErr("");
      if (active && (full || t.messages.length)) onRead(); // chỉ khi thật sự vừa đọc tin mới
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    void load(true);
    const t = window.setInterval(() => void load(false), 3000);
    const s = realtime();
    const on = (ev: C.ChatEvent) => {
      if (ev.room_id === roomId && ev.scope === C.SCOPE) void load(ev.kind === "clear");
    };
    const focus = () => void load(false); // quay lại cửa sổ → đánh dấu đã đọc ngay
    s?.on("chat_event", on);
    window.addEventListener("focus", focus);
    return () => {
      window.clearInterval(t);
      s?.off("chat_event", on);
      window.removeEventListener("focus", focus);
    };
  }, [roomId]); // eslint-disable-line react-hooks/exhaustive-deps -- load đọc ref, chạy lại theo phòng

  useLayoutEffect(() => { // tin mới → cuộn xuống đáy nếu đang ở gần đáy (đang đọc tin cũ thì không giật)
    const b = box.current;
    if (b && stick.current) b.scrollTop = b.scrollHeight;
  }, [msgs]);

  function autoGrow() {
    const el = inp.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }

  async function submit() {
    if (sending || (!text.trim() && !img)) return;
    setSending(true);
    setErr("");
    try {
      await C.send(roomId, text.trim(), img);
      setText("");
      setImg(null);
      stick.current = true;
      requestAnimationFrame(autoGrow);
      await load(false);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSending(false);
      inp.current?.focus();
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  function onPaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    const f = Array.from(e.clipboardData.items).find((i) => i.type.startsWith("image/"))?.getAsFile();
    if (!f) return;
    e.preventDefault();
    C.compressImage(f).then(setImg).catch((x: Error) => setErr(x.message));
  }

  async function doClear(keep: boolean) {
    if (confirm !== (keep ? "keep" : "drop")) return setConfirm(keep ? "keep" : "drop");
    setConfirm("");
    try {
      await C.clear(roomId, keep);
      await load(true);
      onRead();
      if (!keep) C.useChat.setState({ room: null });
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  let day = "";
  return (
    <div className="chat-thread">
      <div className="chat-hd">
        <b>{roomName || "…"}</b>
        <span className="grow" />
        {admin && (
          <>
            <button className="ghost small" onClick={() => void doClear(true)}>
              {confirm === "keep" ? "Bấm lần nữa để xoá nội dung" : "Xoá nội dung"}</button>
            <button className="ghost small danger-text" onClick={() => void doClear(false)}>
              {confirm === "drop" ? "Bấm lần nữa để xoá hội thoại" : "Xoá hội thoại"}</button>
          </>
        )}
      </div>
      <div className="chat-msgs" ref={box}
           onScroll={(e) => {
             const b = e.currentTarget;
             stick.current = b.scrollHeight - b.scrollTop - b.clientHeight < 60;
           }}>
        {!msgs.length && <p className="muted small chat-none">Chưa có tin nhắn.</p>}
        {msgs.map((m) => {
          const d = dayOf(m.created_at);
          const sep = d !== day ? (day = d) : "";
          const mine = m.is_admin === admin;
          const r = reacts[m.id];
          return (
            <div key={m.id}>
              {sep && <div className="chat-day">{sep}</div>}
              <div className={`chat-msg${mine ? " mine" : ""}`}>
                <div className="bubble">
                  {m.image && <ChatImage id={m.id} onZoom={setZoom} />}
                  {m.message && <div className="txt">{m.message}</div>}
                  <div className="meta">{m.is_admin ? `IT · ${m.sender}` : m.sender} · {timeOf(m.created_at)}</div>
                  <div className="rbar">
                    {EMOJI.map((e) => (
                      <button key={e} className={r?.mine === e ? "on" : ""} title="Thả cảm xúc"
                              onClick={() => void C.react(m.id, e).then(() => load(false))}>{e}</button>
                    ))}
                  </div>
                </div>
                {r && Object.keys(r.counts).length > 0 && (
                  <div className="reacts">
                    {Object.entries(r.counts).map(([e, n]) => (
                      <span key={e} className={r.mine === e ? "on" : ""}>{e}{n > 1 ? ` ${n}` : ""}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {err && <p className="error chat-err">{err}</p>}
      {img && (
        <div className="chat-preview">
          <img src={img} alt="Ảnh sắp gửi" onClick={() => setZoom(img)} />
          <button className="ghost small" onClick={() => setImg(null)} title="Bỏ ảnh">×</button>
        </div>
      )}
      <div className="chat-input">
        <textarea ref={inp} rows={1} value={text} placeholder="Nhập tin nhắn… (Enter gửi · Shift+Enter xuống dòng · dán ảnh)"
                  onChange={(e) => {
                    setText(e.target.value);
                    autoGrow();
                  }} onKeyDown={onKey} onPaste={onPaste} />
        <button onClick={() => void submit()} disabled={sending || (!text.trim() && !img)}>Gửi</button>
      </div>
      {zoom && <Zoom src={zoom} onClose={() => setZoom(null)} />}
    </div>
  );
}

function ChatImage({ id, onZoom }: { id: string; onZoom: (u: string) => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [bad, setBad] = useState(false);
  useEffect(() => {
    let live = true;
    C.imageUrl(id).then((u) => live && setUrl(u)).catch(() => live && setBad(true));
    return () => {
      live = false;
    };
  }, [id]);
  if (bad) return <div className="muted small">[Ảnh không tải được]</div>;
  if (!url) return <div className="chat-img loading" />;
  return <img className="chat-img" src={url} alt="Ảnh" loading="lazy" onClick={() => onZoom(url)} />;
}

function Zoom({ src, onClose }: { src: string; onClose: () => void }) {
  useEffect(() => {
    const k = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, [onClose]);
  return (
    <div className="chat-zoom" onClick={onClose} role="dialog" aria-label="Ảnh phóng to">
      <img src={src} alt="Ảnh phóng to" />
      <button className="ghost" onClick={onClose} title="Đóng (Esc)">✕</button>
    </div>
  );
}
