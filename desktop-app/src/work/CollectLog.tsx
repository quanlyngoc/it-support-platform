// Nhật ký kết quả thu bài — mang từ collectlog.js hệ cũ (cùng thứ tự, cùng câu chữ, cùng văn bản "Sao chép log" để giáo
// viên dán vào biên bản như trước): ✔ có bài → ⚠ không có bài → ✖ lỗi / mất kết nối; cùng nhóm thì theo tên máy.
import { useState } from "react";
import type { CollectRow } from "./api";

const MAX_FILES = 40; // dài quá thì gộp "… và N tệp nữa"
const META: Record<string, { icon: string; cls: string }> = {
  ok: { icon: "✔", cls: "ok" }, nofile: { icon: "⚠", cls: "warn" }, nofolder: { icon: "✖", cls: "err" },
  fail: { icon: "✖", cls: "err" }, offline: { icon: "✖", cls: "err" }, running: { icon: "⏳", cls: "warn" },
};

export function statusText(r: CollectRow): string {
  const n = r.files.length || r.count;
  if (r.status === "ok") return n ? `Thu thành công ${n} file` : "Đã nộp về máy chủ";
  if (r.status === "nofile") return "Không có file nào trong thư mục nguồn";
  if (r.status === "nofolder") return "Không tìm thấy thư mục nguồn" + (r.error ? ": " + r.error : "");
  if (r.status === "offline") return "Mất kết nối (chưa nộp)";
  if (r.status === "running") return "Đang chờ máy nộp…";
  return "Thất bại" + (r.error ? ": " + r.error : "");
}

const PRIO: Record<string, number> = { ok: 0, nofile: 1 };
export function sortRows(rows: CollectRow[]): CollectRow[] {
  return [...rows].sort((a, b) => (PRIO[a.status] ?? 2) - (PRIO[b.status] ?? 2) ||
    a.hostname.localeCompare(b.hostname, "vi", { numeric: true }));
}

export function toText(title: string, subtitle: string, rows: CollectRow[], local: Record<string, string>): string {
  const out = [title];
  if (subtitle) out.push(subtitle);
  out.push("");
  for (const r of rows) {
    out.push(`[${(META[r.status] ?? META.fail).icon}] ${r.hostname} — ${statusText(r)}`);
    if (r.status === "ok") {
      if (r.saved_dir) out.push(`    Đã lưu trên máy chủ: THU/${r.saved_dir}`);
      if (local[r.hostname]) out.push(`    Đã lưu về máy: ${local[r.hostname]}`);
      for (const f of r.files) out.push(`        ${f}`);
      if (r.deleted) out.push("    (Đã xoá file gốc trên máy trạm)");
    }
  }
  return out.join("\n");
}

/** Khung nhật ký NGAY trong thẻ Thu bài (không phải hộp thoại lồng — Esc của hộp lồng đóng luôn hộp ngoài). */
export function CollectLog({ title, subtitle, rows, local, onClose }: {
  title: string; subtitle: string; rows: CollectRow[]; local: Record<string, string>; onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const sorted = sortRows(rows);
  const ok = rows.filter((r) => r.status === "ok").length;
  const nofile = rows.filter((r) => r.status === "nofile").length;
  return (
    <section className="wk-logbox" aria-label={title}>
      <h3>{title}</h3>
      {subtitle && <p className="muted small">{subtitle}</p>}
      <p className="wk-sum">
        <span>Tổng: <b>{rows.length}</b> máy</span>
        <span className="ok-text">✔ Có bài: <b>{ok}</b></span>
        <span className="warn-text">⚠ Không có bài: <b>{nofile}</b></span>
        <span className="danger-text">✖ Lỗi/mất kết nối: <b>{rows.length - ok - nofile}</b></span>
      </p>
      <div className="wk-log">
        {sorted.length === 0 && <p className="muted">Không có dữ liệu báo cáo.</p>}
        {sorted.map((r) => {
          const m = META[r.status] ?? META.fail;
          return (
            <div key={r.hostname} className="node">
              <div className="host">🖥️ <b>{r.hostname}</b> <span className={`wk-badge ${m.cls}`}>{m.icon} {statusText(r)}</span></div>
              {r.status === "ok" && r.saved_dir && <div className="line">📁 Đã lưu trên máy chủ: <code>THU/{r.saved_dir}</code></div>}
              {r.status === "ok" && local[r.hostname] && <div className="line">💾 Đã lưu về máy: <code>{local[r.hostname]}</code></div>}
              {r.files.slice(0, MAX_FILES).map((f) => <div key={f} className="line file">📄 {f}</div>)}
              {r.files.length > MAX_FILES && <div className="line file muted">… và {r.files.length - MAX_FILES} tệp nữa</div>}
              {r.status === "ok" && r.deleted && <div className="line danger-text">✖ (Đã xoá file gốc trên máy trạm)</div>}
            </div>
          );
        })}
      </div>
      <div className="actions">
        <button className="ghost" onClick={() => void navigator.clipboard?.writeText(toText(title, subtitle, sorted, local))
          .then(() => setCopied(true))}>{copied ? "Đã sao chép ✓" : "Sao chép log"}</button>
        <button onClick={onClose}>Thu gọn</button>
      </div>
    </section>
  );
}
