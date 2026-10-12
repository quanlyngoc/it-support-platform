// Tự đổi mật khẩu (Sổ tay 8.3 — hệ cũ: "Đổi mật khẩu admin" chỉ cho admin gốc; nay mọi tài khoản Local). Tài khoản AD đổi
// mật khẩu trong AD — Core trả lỗi rõ ràng.
import { useState, type FormEvent } from "react";
import { send } from "../admin/api";
import { Modal } from "./ui";

export function PasswordDialog({ onClose }: { onClose: () => void }) {
  const [oldPw, setOld] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pw.length < 6) return setErr("Mật khẩu mới tối thiểu 6 ký tự.");
    if (pw !== pw2) return setErr("Hai lần nhập mật khẩu mới không khớp.");
    setBusy(true);
    setErr("");
    try {
      await send("POST", "/api/auth/password", { old_password: oldPw, new_password: pw });
      setOk(true);
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Đổi mật khẩu" onClose={onClose} busy={busy}>
      {ok ? (
        <>
          <p className="notice">Đã đổi mật khẩu. Lần đăng nhập sau dùng mật khẩu mới.</p>
          <div className="actions"><button onClick={onClose}>Đóng</button></div>
        </>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="form-grid one">
          <label>Mật khẩu hiện tại
            <input type="password" value={oldPw} onChange={(e) => setOld(e.target.value)} autoComplete="current-password" autoFocus />
          </label>
          <label>Mật khẩu mới (≥ 6 ký tự)
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" />
          </label>
          <label>Nhập lại mật khẩu mới
            <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" />
          </label>
          {err && <p className="error" role="alert">{err}</p>}
          <div className="actions">
            <button type="button" className="ghost" onClick={onClose} disabled={busy}>Huỷ</button>
            <button type="submit" disabled={busy || !oldPw || !pw}>{busy ? "Đang lưu…" : "Đổi mật khẩu"}</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
