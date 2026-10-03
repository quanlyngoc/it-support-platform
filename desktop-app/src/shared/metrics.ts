// Chuyển số liệu agent v2 thành dạng hiển thị — giữ đúng quy ước hệ cũ (components/scripts.html, room_detail.html).

export type Disk = { drive: string; name: string; pct: number; free: string; total: string };

/** `disk_usage` = "C:WIN 10 SSD:62:180.5:476.9|D:Data:11:820.1:931.5" (ổ:tên:%dùng:trống_GB:tổng_GB, nhiều ổ cách "|");
 *  bản agent cũ chỉ có 3 phần "ổ:tên:%". Chuỗi lạ → bỏ qua, không vẽ "undefined". */
export function parseDisks(raw?: string | null): Disk[] {
  if (!raw || typeof raw !== "string" || !raw.includes(":")) return [];
  return raw.split("|").flatMap((s): Disk[] => {
    const p = s.split(":");
    if (!p[0]) return [];
    if (p.length >= 5) return [{ drive: p[0], name: p[1], pct: parseInt(p[2], 10) || 0, free: p[3], total: p[4] }];
    if (p.length === 3) return [{ drive: p[0], name: p[1], pct: parseInt(p[2], 10) || 0, free: "", total: "" }];
    return [];
  });
}

export function diskLabel(d: Disk): string {
  return `${d.drive}: ${d.name} (${d.pct}%${d.total ? ` — trống ${d.free} GB / ${d.total} GB` : ""})`;
}

/** Ngưỡng màu như hệ cũ: > 90% đỏ, > 50% vàng, còn lại xanh. */
export function level(pct: number): "ok" | "warn" | "err" {
  return pct > 90 ? "err" : pct > 50 ? "warn" : "ok";
}

/** Máy giáo viên: tên máy (bỏ ký tự không phải chữ/số) kết thúc bằng "GV" — như `_isGV` của hệ cũ. */
export function isGV(host: string | undefined): boolean {
  return /gv$/i.test(String(host ?? "").replace(/[^a-z0-9]/gi, ""));
}

/** Số ghế để sắp xếp: số cuối tên máy (A6-301-07 → 7); máy GV xếp cuối; không có số → sau các máy có số. */
export function seatNo(host: string | undefined): number {
  if (isGV(host)) return 100000;
  const m = String(host ?? "").match(/(\d+)\s*$/);
  return m ? parseInt(m[1], 10) : 99999;
}

export function fmtTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("vi-VN", { hour12: false });
}
