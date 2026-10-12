// Thành phần giao diện nhỏ dùng chung: thanh đo phần trăm, hộp thoại.
import { useEffect, type ReactNode } from "react";
import { level } from "./metrics";

export function Meter({ pct, title, text }: { pct: number; title?: string; text?: string }) {
  const w = Math.min(100, Math.max(0, pct));
  return (
    <span className={`meter ${level(pct)}`} title={title}>
      <i style={{ width: `${w}%` }} />
      <b>{text ?? `${Math.round(pct)}%`}</b>
    </span>
  );
}

/** Hộp thoại phủ màn hình: Esc hoặc bấm nền để đóng (trừ khi đang bận). */
export function Modal({ title, children, onClose, busy = false, wide = false }: {
  title: string; children: ReactNode; onClose: () => void; busy?: boolean; wide?: boolean;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, busy]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

/** Nút gạt bật/tắt (role="switch") — dùng cho công tắc cơ chế đăng nhập LDAP / SSO (Sổ tay 8.3). */
export function Toggle({ checked, onChange, disabled = false, label }: {
  checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: ReactNode;
}) {
  return (
    <label className={`switch${disabled ? " dis" : ""}`}>
      <input type="checkbox" role="switch" aria-checked={checked} checked={checked} disabled={disabled}
             onChange={(e) => onChange(e.target.checked)} />
      <span className="track"><span className="knob" /></span>
      {label && <span className="switch-label">{label}</span>}
    </label>
  );
}
