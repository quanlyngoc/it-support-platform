// Terminal PowerShell THẬT trên máy trạm (ConPTY, Sổ tay 6.4) — xterm.js. Hai pha như agent 2.7.5.x:
//  1) xác thực tài khoản Windows tại máy (LogonUser) → `pty_auth_response` (Core chỉ cho mở khi CHÍNH người này vừa
//     xác thực đúng, dùng một lần);
//  2) mở ConPTY đúng cỡ khung → luồng `pty_output` (ANSI màu, bảng, con trỏ như console thật); phím gõ → `pty_input`
//     (Tab, mũi tên, lịch sử, Ctrl+C do PSReadLine trên máy xử lý); kéo giãn → `pty_resize`.
// Có chọn chữ thì Ctrl+C = SAO CHÉP (không gửi ngắt); Ctrl+V để trình duyệt dán. Socket nối lại → tự theo dõi lại.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { api, errorMessage } from "../api-client";
import { realtime, request } from "../realtime-client";

type Dev = { id: string; hostname: string; mac?: string };
const mac12 = (m?: string) => String(m ?? "").replace(/[^0-9a-f]/gi, "").toLowerCase();

export function TerminalDialog({ dev, onClose }: { dev: Dev; onClose: () => void }) {
  const [phase, setPhase] = useState<"login" | "auth" | "term" | "ended">("login");
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [error, setError] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  const watch = () => request("watch_device", { device_id: dev.id, kind: "pty" });

  // Đóng: dừng ConPTY + thôi theo dõi (kể cả khi cửa sổ đóng giữa chừng)
  useEffect(() => () => {
    if (started.current) void api().POST("/api/devices/{device_id}/terminal/stop", { params: { path: { device_id: dev.id } } });
    void request("unwatch_device", { device_id: dev.id, kind: "pty" });
  }, [dev.id]);

  async function login(e: FormEvent) {
    e.preventDefault();
    setError("");
    setPhase("auth");
    const w = await watch();
    if (!w.ok) {
      setPhase("login");
      return setError(w.error ?? "Không theo dõi được máy");
    }
    const s = realtime();
    const result = new Promise<{ status: string; msg?: string }>((resolve) => {
      const timer = window.setTimeout(() => {
        s?.off("pty_auth_response", on);
        resolve({ status: "error", msg: "Máy không phản hồi sau 30 giây (máy bận, tắt hoặc mất kết nối)" });
      }, 30000);
      const on = (p: { mac?: string; status: string; msg?: string }) => {
        if (dev.mac && mac12(p.mac) !== mac12(dev.mac)) return;
        window.clearTimeout(timer);
        s?.off("pty_auth_response", on);
        resolve(p);
      };
      s?.on("pty_auth_response", on);
    });
    const r = await api().POST("/api/devices/{device_id}/terminal/validate", {
      params: { path: { device_id: dev.id } }, body: { user: user.trim(), password: pass },
    });
    setPass("");
    if (!r.response.ok) {
      setPhase("login");
      return setError(errorMessage(r.error));
    }
    const a = await result;
    if (a.status !== "success") {
      setPhase("login");
      return setError(a.msg || "Xác thực thất bại");
    }
    setPhase("term");
  }

  // Pha 2: dựng xterm + mở ConPTY đúng cỡ khung (một lần; "ended" giữ nguyên màn hình để còn đọc/sao chép)
  const open = phase === "term" || phase === "ended";
  useEffect(() => {
    if (!open || !box.current) return;
    const term = new Terminal({
      cursorBlink: true, fontSize: 14, scrollback: 5000, fontFamily: "'Cascadia Mono', Consolas, 'Courier New', monospace",
      theme: { background: "#0c1a17", foreground: "#e2ebe8" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(box.current);
    fit.fit();
    term.focus();
    term.attachCustomKeyEventHandler((ev) => {
      if (ev.type !== "keydown" || !ev.ctrlKey) return true;
      const k = ev.key.toLowerCase();
      if (k === "c" && term.hasSelection()) {
        void navigator.clipboard?.writeText(term.getSelection());
        term.clearSelection();
        return false;
      }
      return k !== "v"; // Ctrl+V: để trình duyệt dán → xterm nhận qua onData
    });
    const s = realtime();
    const onOut = (p: { mac?: string; data?: string; closed?: boolean }) => {
      if (dev.mac && mac12(p.mac) !== mac12(dev.mac)) return;
      if (p.data) term.write(p.data);
      if (p.closed) setPhase("ended");
    };
    const onReconnect = () => void watch(); // nối lại socket → vào lại room theo dõi
    s?.on("pty_output", onOut);
    s?.on("connect", onReconnect);
    const sub1 = term.onData((data) => void request("pty_input", { device_id: dev.id, data }));
    let rt: number | undefined;
    const sub2 = term.onResize(({ cols, rows }) => {
      window.clearTimeout(rt);
      rt = window.setTimeout(() => void request("pty_resize", { device_id: dev.id, cols, rows }), 150);
    });
    const ro = new ResizeObserver(() => fit.fit());
    ro.observe(box.current);
    void (async () => {
      const r = await api().POST("/api/devices/{device_id}/terminal/start", {
        params: { path: { device_id: dev.id } }, body: { cols: term.cols, rows: term.rows },
      });
      if (!r.response.ok) {
        term.write(`\r\n\x1b[31m${errorMessage(r.error)}\x1b[0m\r\n`);
        setPhase("ended");
      } else {
        started.current = true;
      }
    })();
    return () => {
      ro.disconnect();
      sub1.dispose();
      sub2.dispose();
      s?.off("pty_output", onOut);
      s?.off("connect", onReconnect);
      term.dispose();
    };
  }, [open, dev.id]); // eslint-disable-line react-hooks/exhaustive-deps -- watch() dựng lại mỗi lần render

  return (
    <div className="term-back" role="dialog" aria-label={`Terminal ${dev.hostname}`}>
      <div className="term-box">
        <div className="term-bar">
          <b>Terminal — {dev.hostname}</b>
          <span className="muted small">
            {phase === "term" ? "PowerShell trên máy trạm · có chọn chữ thì Ctrl+C là sao chép"
              : phase === "ended" ? "Phiên đã kết thúc" : "Xác thực tài khoản Windows của máy"}
          </span>
          <span className="grow" />
          <button className="ghost" onClick={onClose}>Đóng</button>
        </div>
        {phase === "login" || phase === "auth" ? (
          <form className="form term-login" onSubmit={(e) => void login(e)}>
            <label>Tài khoản Windows<input value={user} onChange={(e) => setUser(e.target.value)} autoFocus
                                            placeholder="vd. Administrator hoặc DOMAIN\user" autoComplete="off" /></label>
            <label>Mật khẩu<input type="password" value={pass} onChange={(e) => setPass(e.target.value)}
                                   autoComplete="new-password" /></label>
            <p className="muted small">Máy trạm tự kiểm tài khoản (như đăng nhập vào máy). Đúng thì mới mở PowerShell.</p>
            {error && <p className="error">{error}</p>}
            <div className="actions">
              <button type="submit" disabled={phase === "auth" || !user.trim() || !pass}>
                {phase === "auth" ? "Đang xác thực…" : "Mở terminal"}
              </button>
            </div>
          </form>
        ) : (
          <div className="term-screen" ref={box} />
        )}
      </div>
    </div>
  );
}
