// Chuyển phòng (Move PC — 1 hoặc nhiều máy) và Xoá máy, mỗi thao tác có hộp xác nhận (Sổ tay 5.2; hệ cũ §8.1).
// Core kiểm quyền `device.manage` + phạm vi phòng; ở đây chỉ hiện lỗi Core trả về.
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, getJson } from "../api-client";
import type { Device, MoveResult } from "../api-client/types";
import { Modal } from "../shared/ui";

type Target = Pick<Device, "id" | "hostname">;

export function MoveDialog({ devices, currentRoom, onClose, onDone }: {
  devices: Target[]; currentRoom?: string; onClose: () => void; onDone: (msg: string) => void;
}) {
  const qc = useQueryClient();
  const targets = useQuery({
    queryKey: ["move-targets"],
    queryFn: () => getJson<{ items: string[] }>("/api/rooms/move-targets"),
  });
  const [room, setRoom] = useState("");
  const [seat, setSeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const one = devices.length === 1;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!room) return setError("Chưa chọn phòng đích");
    setBusy(true);
    setError("");
    const res = one
      ? await api().POST("/api/devices/{device_id}/move", {
        params: { path: { device_id: devices[0].id } }, body: { room_name: room, seat: seat.trim() },
      })
      : await api().POST("/api/devices/move-bulk", { body: { device_ids: devices.map((d) => d.id), room_name: room } });
    setBusy(false);
    if (!res.response.ok) return setError(errorMessage(res.error));
    const r = res.data as unknown as MoveResult;
    void qc.invalidateQueries(); // số máy/online của cả phòng cũ lẫn phòng mới đổi — lấy lại số tuyệt đối
    onDone(`Đã chuyển ${r.moved.length} máy sang ${r.room_name}` +
      (r.skipped.length ? ` (bỏ qua ${r.skipped.length} máy không còn / ngoài phạm vi)` : ""));
  }

  const rooms = (targets.data?.items ?? []).filter((r) => r !== currentRoom);
  return (
    <Modal title={one ? `Chuyển phòng — ${devices[0].hostname}` : `Chuyển ${devices.length} máy sang phòng khác`}
           onClose={onClose} busy={busy}>
      <form className="form" onSubmit={submit}>
        {!one && <p className="muted small">{devices.map((d) => d.hostname).join(", ")}</p>}
        <label>
          Phòng đích
          <select value={room} onChange={(e) => setRoom(e.target.value)} disabled={busy || targets.isPending} autoFocus>
            <option value="">{targets.isPending ? "Đang tải…" : "— Chọn phòng —"}</option>
            {rooms.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        {one && (
          <label>
            <span>Số vị trí trong phòng <span className="muted">(không bắt buộc)</span></span>
            <input value={seat} onChange={(e) => setSeat(e.target.value.replace(/\D/g, "").slice(0, 4))}
                   inputMode="numeric" placeholder="vd 12" disabled={busy} />
          </label>
        )}
        <p className="muted small">
          Dùng khi máy đã chuyển sang phòng khác nhưng tên máy chưa đổi. Khi tên máy đổi đúng phòng đích, ghi chú
          "chuyển tay" tự gỡ.
        </p>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" className="ghost" onClick={onClose} disabled={busy}>Huỷ</button>
          <button type="submit" disabled={busy || !room}>{busy ? "Đang chuyển…" : "Chuyển"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function DeleteDialog({ device, onClose, onDone }: {
  device: Pick<Device, "id" | "hostname" | "is_online">; onClose: () => void; onDone: (msg: string) => void;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setBusy(true);
    setError("");
    const res = await api().DELETE("/api/devices/{device_id}", { params: { path: { device_id: device.id } } });
    setBusy(false);
    if (!res.response.ok) return setError(errorMessage(res.error));
    void qc.invalidateQueries();
    onDone(`Đã xoá ${device.hostname} khỏi danh sách (bản ghi đã lưu vào kho lưu trữ)`);
  }

  return (
    <Modal title={`Xoá máy ${device.hostname}?`} onClose={onClose} busy={busy}>
      <p>Máy bị bỏ khỏi danh sách phòng. Bản ghi cũ được chép vào kho lưu trữ (xem ở nhật ký thay đổi máy); lịch sử
        sự cố giữ nguyên.</p>
      {device.is_online && (
        <p className="warn-box">Máy đang <b>online</b>: nhịp tim kế tiếp sẽ thêm lại máy như máy mới, vào phòng suy từ
          tên máy. Chỉ xoá máy đã thu hồi / không còn dùng.</p>
      )}
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="button" className="ghost" onClick={onClose} disabled={busy} autoFocus>Huỷ</button>
        <button type="button" className="danger" onClick={() => void confirm()} disabled={busy}>
          {busy ? "Đang xoá…" : "Xoá máy"}
        </button>
      </div>
    </Modal>
  );
}
