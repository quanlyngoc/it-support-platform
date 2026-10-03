// Khung ứng dụng sau đăng nhập: thanh trên cùng hiện tổ chức + người dùng (đặc tả §10), điều hướng, đăng xuất,
// kênh realtime, dải đỏ khi mất kết nối (banner B1 của hệ cũ) và dải báo có bản Desktop mới.
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, NavLink, Outlet } from "react-router";
import { api } from "../api-client";
import type { ListResult, Room } from "../api-client/types";
import { connectRealtime, disconnectRealtime, useRealtime, type BatchDeviceUpdate } from "../realtime-client";
import { useSession } from "../session/store";
import { notifyOs } from "./notify";
import { checkUpdate, installUpdate, useUpdate } from "./updater";

type IncidentNew = { hostname: string; room_name?: string; title: string; description?: string };

const KIEM_CAP_NHAT_MS = 6 * 3600 * 1000;

export function Layout() {
  const { token, session, baseUrl, logout } = useSession();
  const { connected, everConnected } = useRealtime();
  const qc = useQueryClient();

  useEffect(() => {
    if (!token) return;
    const s = connectRealtime(baseUrl, token, () => void qc.invalidateQueries());
    s.on("batch_device_update", (p: BatchDeviceUpdate) => {
      // GHI ĐÈ số tuyệt đối theo room_stats — cấm cộng/trừ 1 (bài học 10.10 hệ cũ)
      qc.setQueryData<ListResult<Room>>(["rooms"], (old) =>
        old && {
          ...old,
          items: old.items.map((r) => (r.id in p.room_stats ? { ...r, online: p.room_stats[r.id] } : r)),
        });
    });
    s.on("incident_new", (p: IncidentNew) => {
      void qc.invalidateQueries({ queryKey: ["incidents"] }); // lấy lại số tuyệt đối, không tự cộng 1
      void notifyOs(`Sự cố: ${p.title}`, [p.hostname, p.room_name].filter(Boolean).join(" · "));
    });
    return () => disconnectRealtime();
  }, [token, baseUrl, qc]);

  useEffect(() => {
    const first = setTimeout(() => void checkUpdate(), 5000); // để màn hình đầu tiên tải xong trước
    const every = setInterval(() => void checkUpdate(), KIEM_CAP_NHAT_MS);
    return () => {
      clearTimeout(first);
      clearInterval(every);
    };
  }, []);

  if (!token || !session) return <Navigate to="/login" replace />;

  async function signOut() {
    try {
      await api().POST("/api/auth/logout");
    } finally {
      disconnectRealtime();
      logout();
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Phenikaa IT Monitor</span>
        <nav>
          <NavLink to="/" end>Tổng quan</NavLink>
          <NavLink to="/about">Giới thiệu</NavLink>
        </nav>
        <span className="who">
          <b>{session.tenant_code}</b> · {session.username}
          {session.is_super && <span className="badge">Super Admin</span>}
        </span>
        <button className="ghost" onClick={signOut}>Đăng xuất</button>
      </header>
      <div className="strips">
        {everConnected && !connected && (
          <div className="lost" role="status">MẤT KẾT NỐI MÁY CHỦ. Đang kết nối lại…</div>
        )}
        <UpdateStrip />
      </div>
      <div className="content">
        <Outlet />
      </div>
    </div>
  );
}

function UpdateStrip() {
  const { update, installing, progress, error } = useUpdate();
  if (!update) return null;
  return (
    <div className="update-strip" role="status">
      {installing ? (
        <span>Đang tải bản {update.version}{progress !== null ? ` — ${progress}%` : "…"} Ứng dụng sẽ tự mở lại.</span>
      ) : (
        <>
          <span>Có bản mới <b>{update.version}</b> (đang dùng {update.currentVersion}).</span>
          <button onClick={() => void installUpdate()}>Cập nhật và mở lại</button>
        </>
      )}
      {error && <span className="update-err">{error}</span>}
    </div>
  );
}
