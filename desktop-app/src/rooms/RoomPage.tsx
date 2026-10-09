// Chi tiết phòng (Sổ tay 5.2): mọi máy của phòng với CPU/RAM/ổ đĩa theo giây, model, service tag, IP/MAC, phiên bản
// agent, máy GV, sự cố đang mở; chọn nhiều máy để Chuyển phòng; Chuyển / Xoá từng máy (quyền device.manage).
// Đăng ký room realtime của phòng; mỗi batch_device_update GHI ĐÈ trạng thái từng máy + số online tuyệt đối. Mọi chỗ
// vẽ số đo bọc is_online — máy offline KHÔNG có cpu_usage/ram_usage/disk_usage (bài học 10.11 hệ cũ).
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";
import { getJson } from "../api-client";
import type { Device, Incident, ListResult, RoomDetail } from "../api-client/types";
import { DeleteDialog, MoveDialog } from "../devices/DeviceDialogs";
import { realtime, request, useRealtime, type BatchDeviceUpdate } from "../realtime-client";
import { diskLabel, isGV, parseDisks, seatNo } from "../shared/metrics";
import { useCan } from "../shared/perm";
import { Meter } from "../shared/ui";
import { RoomMap } from "./map/RoomMap";
import { normalize, type MapResponse } from "./map/model";
import { LiveGrid } from "./live/LiveGrid";
import { openVnc } from "../devices/vnc";
import { ControlHost, ControlMenu, type ControlKind, type ControlTarget } from "../control/ControlDialog";
import type { WorkPreset } from "../work/WorkDialog";

// Trình quản lý tệp chỉ nạp khi mở (Sổ tay 7.2)
const FileManager = lazy(() => import("../files/FileManager").then((m) => ({ default: m.FileManager })));
const WorkDialog = lazy(() => import("../work/WorkDialog").then((m) => ({ default: m.WorkDialog })));

export function RoomPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const connected = useRealtime((s) => s.connected);
  const canManage = useCan("device.manage");
  const slow = connected ? 30000 : 5000; // có realtime: chỉ đối soát chậm; mất realtime: hỏi nhanh
  const q = useQuery({
    queryKey: ["room", id],
    queryFn: () => getJson<RoomDetail>(`/api/rooms/${encodeURIComponent(id)}`),
    refetchInterval: slow,
  });
  const inc = useQuery({
    queryKey: ["incidents", "room", id],
    queryFn: () => getJson<ListResult<Incident>>(`/api/incidents?status=OPEN&limit=1000&room_id=${encodeURIComponent(id)}`),
    refetchInterval: slow,
  });
  const [filter, setFilter] = useState("");
  const [onlyOnline, setOnlyOnline] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [moving, setMoving] = useState<Device[] | null>(null);
  const [deleting, setDeleting] = useState<Device | null>(null);
  const [notice, setNotice] = useState("");
  const navigate = useNavigate();
  const canVnc = useCan("remote.vnc");
  const canControl = useCan("device.control");
  const canSelect = canManage || canControl;
  const [ctl, setCtl] = useState<{ kind: ControlKind; target: ControlTarget } | null>(null);
  const [files, setFiles] = useState(false);
  const [work, setWork] = useState<WorkPreset | null>(null);
  const canMapEdit = useCan("room_map.edit");
  const [view, setView] = useState<"list" | "map" | "live">(() => {
    try {
      const v = sessionStorage.getItem("rd_view");
      return v === "map" || v === "live" ? v : "list";
    } catch {
      return "list";
    }
  });
  const shownView = view === "live" && !canVnc ? "list" : view;
  const mapQ = useQuery({
    queryKey: ["room-map", id],
    queryFn: () => getJson<MapResponse>(`/api/rooms/${encodeURIComponent(id)}/map`),
    enabled: shownView === "live",
  });
  const pickView = (v: "list" | "map" | "live") => {
    setView(v);
    try {
      sessionStorage.setItem("rd_view", v);
    } catch {
      // không có sessionStorage → chỉ nhớ trong lúc mở trang
    }
  };

  useEffect(() => {
    setSel(new Set());
    setNotice("");
  }, [id]);

  useEffect(() => {
    const s = realtime();
    if (!s || !connected) return;
    void request("subscribe_room", { room_id: id });
    const onBatch = (p: BatchDeviceUpdate) => {
      if (p.room_id !== id) return;
      let unknown = false;
      qc.setQueryData<RoomDetail>(["room", id], (old) => {
        if (!old) return old;
        const known = new Set(old.devices.map((d) => d.id));
        unknown = p.devices.some((d) => d.device_id && !known.has(d.device_id));
        const byId = new Map(p.devices.filter((d) => d.device_id).map((d) => [d.device_id as string, d]));
        const devices = old.devices.map((d): Device => {
          const u = byId.get(d.id);
          if (!u) return d;
          const { cpu_usage: _c, ram_usage: _r, disk_usage: _d, ...rest } = d; // offline → bỏ số đo cũ
          return u.is_online
            ? { ...rest, is_online: true, cpu_usage: u.cpu_usage, ram_usage: u.ram_usage, disk_usage: u.disk_usage,
                client_version: u.client_version ?? d.client_version }
            : { ...rest, is_online: false };
        });
        return { ...old, devices, online: p.room_stats[id] ?? old.online };
      });
      if (unknown) void qc.invalidateQueries({ queryKey: ["room", id] }); // máy vừa chuyển vào / máy mới → tải lại
    };
    s.on("batch_device_update", onBatch);
    return () => {
      s.off("batch_device_update", onBatch);
      void request("unsubscribe_room", { room_id: id });
    };
  }, [id, connected, qc]);

  const incByHost = useMemo(() => {
    const m = new Map<string, Incident[]>();
    for (const i of inc.data?.items ?? []) {
      const k = String(i.hostname ?? "").toUpperCase();
      m.set(k, [...(m.get(k) ?? []), i]);
    }
    return m;
  }, [inc.data]);

  if (q.isPending) return <p className="muted">Đang tải…</p>;
  if (q.isError) return <p className="error">{q.error.message}</p>;
  const r = q.data;
  const f = filter.trim().toLowerCase();
  const devices = [...r.devices]
    .sort((a, b) => seatNo(a.hostname) - seatNo(b.hostname) || a.hostname.localeCompare(b.hostname))
    .filter((d) => (!onlyOnline || d.is_online) &&
      (!f || [d.hostname, d.ip, d.mac, d.serial, d.model].some((x) => String(x ?? "").toLowerCase().includes(f))));
  const allSel = devices.length > 0 && devices.every((d) => sel.has(d.id));
  const toggle = (did: string) => setSel((s) => {
    const n = new Set(s);
    if (n.has(did)) n.delete(did);
    else n.add(did);
    return n;
  });
  const selected = r.devices.filter((d) => sel.has(d.id));
  const done = (msg: string) => {
    setMoving(null);
    setDeleting(null);
    setSel(new Set());
    setNotice(msg);
  };

  return (
    <section>
      <p><Link to="/rooms">← Phòng máy</Link></p>
      <div className="dash-head">
        <h1>{r.name} <small className="muted">{r.online} / {r.total} online</small></h1>
        <div className="toolbar">
          {canControl && (
            <ControlMenu target={{ kind: "room", roomId: id, name: r.name }}
                         onPick={(kind, target) => setCtl({ kind, target })} />
          )}
          {canControl && (
            <button className="ghost" onClick={() => setFiles(true)} title="Trình quản lý tệp 2 khung (máy trạm ⇄ máy trạm / máy bạn)">
              📂 Tệp
            </button>
          )}
          {canControl && (
            <button className="ghost" onClick={() => setWork({ rooms: [{ id, name: r.name }] })}
                    title="Giao bài / thu bài / tệp đã giao cho cả phòng">📤 Giao/Thu bài</button>
          )}
          <div className="seg" role="tablist" aria-label="Kiểu xem">
            <button role="tab" aria-selected={shownView === "list"} className={shownView === "list" ? "on" : ""}
                    onClick={() => pickView("list")}>Danh sách</button>
            <button role="tab" aria-selected={shownView === "map"} className={shownView === "map" ? "on" : ""}
                    onClick={() => pickView("map")}>Sơ đồ</button>
            {canVnc && (
              <button role="tab" aria-selected={shownView === "live"} className={shownView === "live" ? "on" : ""}
                      onClick={() => pickView("live")}>Màn hình</button>
            )}
          </div>
          {shownView === "list" && (
            <>
              <label className="check"><input type="checkbox" checked={onlyOnline}
                                              onChange={(e) => setOnlyOnline(e.target.checked)} /> Chỉ máy online</label>
              <input className="search" value={filter} onChange={(e) => setFilter(e.target.value)}
                     placeholder="Tìm tên máy / IP / MAC / service tag" aria-label="Tìm máy" />
            </>
          )}
        </div>
      </div>
      {notice && <p className="notice" role="status">{notice}</p>}
      {canSelect && sel.size > 0 && (
        <div className="bulkbar">
          <span>Đã chọn <b>{sel.size}</b> máy</span>
          {canControl && (
            <ControlMenu target={{ kind: "devices", ids: selected.map((d) => d.id), names: selected.map((d) => d.hostname) }}
                         onPick={(kind, target) => setCtl({ kind, target })} />
          )}
          {canControl && (
            <button className="ghost" onClick={() => setWork({ rooms: [{ id, name: r.name }],
              deviceIds: selected.map((d) => d.id), deviceNames: selected.map((d) => d.hostname) })}>Giao/Thu bài…</button>
          )}
          {canManage && <button onClick={() => setMoving(selected)}>Chuyển phòng…</button>}
          <button className="ghost" onClick={() => setSel(new Set())}>Bỏ chọn</button>
        </div>
      )}
      {shownView === "live" ? (
        <LiveGrid room={r} map={mapQ.data?.map ? normalize(mapQ.data.map) : null} canEdit={canMapEdit}
                  onOpenDevice={(did) => navigate(`/devices/${did}`)} />
      ) : shownView === "map" ? (
        <RoomMap roomId={id} roomName={r.name} devices={r.devices} devSel={sel} onToggleDevice={toggle}
                 onOpenDevice={(did) => navigate(`/devices/${did}`)} />
      ) : (
      <>
      <table className="grid devices">
        <thead>
          <tr>
            {canSelect && (
              <th className="c-sel">
                <input type="checkbox" aria-label="Chọn tất cả" checked={allSel}
                       onChange={() => setSel(allSel ? new Set() : new Set(devices.map((d) => d.id)))} />
              </th>
            )}
            <th>Máy</th><th>Trạng thái</th><th>CPU</th><th>RAM</th><th>Ổ đĩa</th><th>IP · MAC</th>
            <th>Model · Service tag</th><th>Agent</th><th>Sự cố</th>{(canManage || canVnc) && <th />}
          </tr>
        </thead>
        <tbody>
          {devices.map((d) => (
            <Row key={d.id} d={d} canManage={canManage} canVnc={canVnc} canSelect={canSelect} selected={sel.has(d.id)}
                 onToggle={() => toggle(d.id)} incidents={incByHost.get(d.hostname.toUpperCase()) ?? []}
                 onMove={() => setMoving([d])} onDelete={() => setDeleting(d)}
                 onVnc={() => openVnc(d).catch((e: Error) => setNotice(e.message))} />
          ))}
        </tbody>
      </table>
      {devices.length === 0 && <p className="muted">{f || onlyOnline ? "Không có máy khớp." : "Phòng chưa có máy."}</p>}
      </>
      )}
      {moving && <MoveDialog devices={moving} currentRoom={r.name} onClose={() => setMoving(null)} onDone={done} />}
      {deleting && <DeleteDialog device={deleting} onClose={() => setDeleting(null)} onDone={done} />}
      {ctl && <ControlHost kind={ctl.kind} target={ctl.target} onClose={() => setCtl(null)} />}
      {files && (
        <Suspense fallback={<p className="muted">Đang mở trình quản lý tệp…</p>}>
          <FileManager roomId={id} onClose={() => setFiles(false)} />
        </Suspense>
      )}
      {work && (
        <Suspense fallback={<p className="muted">Đang mở giao/thu bài…</p>}>
          <WorkDialog preset={work} onClose={() => setWork(null)} />
        </Suspense>
      )}
    </section>
  );
}

function Row({ d, canManage, canVnc, canSelect, selected, onToggle, incidents, onMove, onDelete, onVnc }: {
  d: Device; canManage: boolean; canVnc: boolean; canSelect: boolean; selected: boolean; onToggle: () => void;
  incidents: Incident[];
  onMove: () => void; onDelete: () => void; onVnc: () => void;
}) {
  const disks = d.is_online ? parseDisks(d.disk_usage) : [];
  return (
    <tr className={`${d.is_online ? "" : "off"}${selected ? " sel" : ""}`}>
      {canSelect && (
        <td className="c-sel"><input type="checkbox" checked={selected} onChange={onToggle}
                                     aria-label={`Chọn ${d.hostname}`} /></td>
      )}
      <td>
        <Link to={`/devices/${d.id}`} className="host">{d.hostname}</Link>
        {isGV(d.hostname) && <span className="badge gv" title="Máy giáo viên">GV</span>}
        {d.room_override && (
          <span className="badge" title={`Chuyển tay (Move PC)${d.move_seat ? ` — vị trí ${d.move_seat}` : ""}`}>
            chuyển tay{d.move_seat ? ` · ${d.move_seat}` : ""}
          </span>
        )}
      </td>
      <td>
        <span className={`dot ${d.is_online ? "on" : "off"}`} />
        {d.is_online ? (d.channel === "http" ? "Online (mất kênh lệnh)" : "Online") : "Offline"}
      </td>
      <td>{d.is_online && d.cpu_usage !== undefined ? <Meter pct={d.cpu_usage} /> : "—"}</td>
      <td>{d.is_online && d.ram_usage !== undefined ? <Meter pct={d.ram_usage} /> : "—"}</td>
      <td className="disks">
        {disks.length ? disks.map((k) => <Meter key={k.drive} pct={k.pct} title={diskLabel(k)} text={`${k.drive}: ${k.pct}%`} />)
          : "—"}
      </td>
      <td className="two"><span>{d.ip ?? ""}</span><span className="muted">{d.mac ?? ""}</span></td>
      <td className="two"><span>{d.model ?? ""}</span><span className="muted">{d.serial ?? ""}</span></td>
      <td>{d.client_version ?? ""}</td>
      <td>
        {incidents.length > 0 && (
          <span className="badge warn" title={incidents.map((i) => i.title).join("\n")}>{incidents.length}</span>
        )}
      </td>
      {(canManage || canVnc) && (
        <td className="row-actions">
          {canVnc && d.is_online && (
            <button className="ghost small" onClick={onVnc} title="Xem / điều khiển màn hình">Màn hình</button>
          )}
          {canManage && <button className="ghost small" onClick={onMove}>Chuyển</button>}
          {canManage && <button className="ghost small danger-text" onClick={onDelete}>Xoá</button>}
        </td>
      )}
    </tr>
  );
}
