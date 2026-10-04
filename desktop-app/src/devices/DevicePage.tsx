// Chi tiết một máy (Sổ tay 5.2): số đo theo giây (chỉ khi online — bài học 10.11), cấu hình phần cứng, pin CMOS, phiên
// bản agent, sự cố của máy, nhật ký thay đổi định danh (tráo phần cứng / đổi serial / đổi MAC — quyền
// machine_events.view), Chuyển phòng / Xoá máy (quyền device.manage).
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";
import { getJson } from "../api-client";
import type { Device, Incident, ListResult, MachineEvent } from "../api-client/types";
import { realtime, request, useRealtime, type BatchDeviceUpdate } from "../realtime-client";
import { diskLabel, fmtTime, isGV, parseDisks } from "../shared/metrics";
import { useCan } from "../shared/perm";
import { Meter } from "../shared/ui";
import { DeleteDialog, MoveDialog } from "./DeviceDialogs";
import { openVnc } from "./vnc";
import { ControlDialog, ControlMenu, type ControlKind } from "../control/ControlDialog";

const SU_KIEN: Record<string, string> = { trao_phan_cung: "Tráo phần cứng", doi_serial: "Đổi serial", doi_mac: "Đổi MAC" };
const TRANG_THAI: Record<Incident["status"], string> = { PENDING: "Chờ xử lý", PROCESSING: "Đang xử lý", DONE: "Xong" };

export function DevicePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const connected = useRealtime((s) => s.connected);
  const canManage = useCan("device.manage");
  const canEvents = useCan("machine_events.view");
  const canVnc = useCan("remote.vnc");
  const canControl = useCan("device.control");
  const [ctl, setCtl] = useState<ControlKind | null>(null);
  const [dialog, setDialog] = useState<"move" | "delete" | null>(null);
  const [notice, setNotice] = useState("");
  const q = useQuery({
    queryKey: ["device", id],
    queryFn: () => getJson<Device>(`/api/devices/${encodeURIComponent(id)}`),
    refetchInterval: connected ? 30000 : 5000,
  });
  const host = q.data?.hostname ?? "";
  const roomId = q.data?.room_id ?? "";
  const inc = useQuery({
    queryKey: ["incidents", "host", host],
    queryFn: () => getJson<ListResult<Incident>>(`/api/incidents?limit=50&hostname=${encodeURIComponent(host)}`),
    enabled: !!host,
  });
  const ev = useQuery({
    queryKey: ["machine-events", host],
    queryFn: () => getJson<{ events: MachineEvent[] }>(`/api/devices/events?limit=100&q=${encodeURIComponent(host)}`),
    enabled: !!host && canEvents,
  });

  useEffect(() => {
    const s = realtime();
    if (!s || !connected || !roomId) return;
    void request("subscribe_room", { room_id: roomId });
    const onBatch = (p: BatchDeviceUpdate) => {
      const u = p.devices.find((d) => d.device_id === id);
      if (!u) return;
      qc.setQueryData<Device>(["device", id], (old) => {
        if (!old) return old;
        const { cpu_usage: _c, ram_usage: _r, disk_usage: _d, ...rest } = old;
        return u.is_online
          ? { ...rest, is_online: true, cpu_usage: u.cpu_usage, ram_usage: u.ram_usage, disk_usage: u.disk_usage,
              client_version: u.client_version ?? old.client_version }
          : { ...rest, is_online: false };
      });
    };
    s.on("batch_device_update", onBatch);
    return () => {
      s.off("batch_device_update", onBatch);
      void request("unsubscribe_room", { room_id: roomId });
    };
  }, [id, roomId, connected, qc]);

  if (q.isPending) return <p className="muted">Đang tải…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;
  const d = q.data;
  const disks = d.is_online ? parseDisks(d.disk_usage) : [];
  const cmosHet = String(d.cmos_battery ?? "").includes("Hết pin");
  const events = (ev.data?.events ?? []).filter((e) => e.hostname === host || e.other_host === host);

  return (
    <section>
      <p>{d.room_id ? <Link to={`/rooms/${d.room_id}`}>← {d.room_name ?? "Phòng"}</Link> : <Link to="/rooms">← Phòng máy</Link>}</p>
      <div className="dash-head">
        <h1>
          {d.hostname}
          {isGV(d.hostname) && <span className="badge gv">GV</span>}
          {" "}<small className="muted"><span className={`dot ${d.is_online ? "on" : "off"}`} />
            {d.is_online ? (d.channel === "http" ? "Online (mất kênh lệnh)" : "Online") : "Offline"}</small>
        </h1>
        {(canManage || canVnc || canControl) && (
          <div className="toolbar">
            {canControl && (
              <ControlMenu target={{ kind: "devices", ids: [id], names: [host] }} onPick={(k) => setCtl(k)} />
            )}
            {canVnc && d.is_online && (
              <button onClick={() => openVnc(d).catch((e: Error) => setNotice(e.message))}>Điều khiển màn hình</button>
            )}
            {canManage && <button className={canVnc && d.is_online ? "ghost" : ""} onClick={() => setDialog("move")}>Chuyển phòng…</button>}
            {canManage && <button className="ghost danger-text" onClick={() => setDialog("delete")}>Xoá máy…</button>}
          </div>
        )}
      </div>
      {notice && <p className="notice" role="status">{notice}</p>}

      {d.is_online ? (
        <div className="live">
          <div><span>CPU</span>{d.cpu_usage !== undefined ? <Meter pct={d.cpu_usage} /> : "—"}</div>
          <div><span>RAM</span>{d.ram_usage !== undefined ? <Meter pct={d.ram_usage} /> : "—"}</div>
          {disks.map((k) => (
            <div key={k.drive}><span title={diskLabel(k)}>Ổ {k.drive}: {k.name}</span>
              <Meter pct={k.pct} title={diskLabel(k)} text={k.total ? `${k.pct}% · trống ${k.free}/${k.total} GB` : undefined} />
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">Máy đang tắt — {d.last_heartbeat_at ? `nhịp tim cuối ${fmtTime(d.last_heartbeat_at)}` : "chưa có nhịp tim"}.</p>
      )}

      <h2>Cấu hình</h2>
      <dl className="kv">
        <dt>Phòng</dt>
        <dd>{d.room_name ?? "—"}{d.room_override && <span className="badge">chuyển tay{d.move_seat ? ` · vị trí ${d.move_seat}` : ""}</span>}</dd>
        <Kv k="Model" v={d.model} />
        <Kv k="Service tag / Serial" v={d.serial} />
        <Kv k="CPU" v={d.cpu} />
        <Kv k="RAM" v={d.ram} />
        <Kv k="Mainboard" v={d.mainboard} />
        <Kv k="Ổ cứng" v={d.disk} />
        <Kv k="Card mạng" v={d.network} />
        <Kv k="IP" v={d.ip} />
        <Kv k="IP máy chủ thấy" v={d.seen_ip !== d.ip ? d.seen_ip : undefined} />
        <Kv k="MAC" v={d.mac} />
        <dt>Pin CMOS</dt>
        <dd className={cmosHet ? "err" : ""}>{d.cmos_battery || "—"}</dd>
        <Kv k="Nhiệt độ CPU" v={d.cpu_temp} />
        <Kv k="Quạt CPU" v={d.cpu_fan} />
        <Kv k="Phiên bản agent" v={d.client_version} />
        <Kv k="Nhịp tim cuối" v={fmtTime(d.last_heartbeat_at)} />
        <Kv k="Thêm vào danh sách" v={fmtTime(d.created_at)} />
      </dl>

      <h2>Sự cố</h2>
      {inc.data && inc.data.items.length > 0 ? (
        <table className="grid">
          <thead><tr><th>Thời điểm</th><th>Sự cố</th><th>Chi tiết</th><th>Trạng thái</th></tr></thead>
          <tbody>
            {inc.data.items.map((i) => (
              <tr key={i.id}>
                <td>{fmtTime(i.created_at)}</td><td><b>{i.title}</b></td><td>{i.description}</td>
                <td>{TRANG_THAI[i.status] ?? i.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted">{inc.isPending ? "Đang tải…" : "Chưa có sự cố."}</p>}

      {canEvents && (
        <>
          <h2>Nhật ký thay đổi máy</h2>
          {events.length > 0 ? (
            <table className="grid">
              <thead><tr><th>Thời điểm</th><th>Loại</th><th>Ghi chú</th><th>Cũ → mới</th></tr></thead>
              <tbody>
                {events.map((e, n) => (
                  <tr key={n}>
                    <td>{fmtTime(e.created_at)}</td><td>{SU_KIEN[e.event] ?? e.event}</td><td>{e.note}</td>
                    <td>{[e.old_value, e.new_value].filter(Boolean).join(" → ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted">{ev.isPending ? "Đang tải…" : "Không có thay đổi định danh."}</p>}
        </>
      )}

      {ctl && (
        <ControlDialog kind={ctl} target={{ kind: "devices", ids: [d.id], names: [d.hostname] }}
                       onClose={() => setCtl(null)} />
      )}
      {dialog === "move" && (
        <MoveDialog devices={[d]} currentRoom={d.room_name} onClose={() => setDialog(null)}
                    onDone={(m) => { setDialog(null); setNotice(m); }} />
      )}
      {dialog === "delete" && (
        <DeleteDialog device={d} onClose={() => setDialog(null)}
                      onDone={() => navigate(d.room_id ? `/rooms/${d.room_id}` : "/rooms", { replace: true })} />
      )}
    </section>
  );
}

function Kv({ k, v }: { k: string; v?: string | null }) {
  if (!v) return null;
  return (<><dt>{k}</dt><dd>{v}</dd></>);
}
