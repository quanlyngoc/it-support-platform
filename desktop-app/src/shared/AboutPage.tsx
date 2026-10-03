// Giới thiệu (đặc tả §6: "Trợ giúp → Giới thiệu" thay cho FB_VER / CHATBOX_VER của web cũ): phiên bản ứng dụng, máy chủ
// Core đang nối + phiên bản Core, trạng thái kênh realtime, và nút kiểm tra cập nhật thủ công.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api-client";
import type { Health } from "../api-client/types";
import { useRealtime } from "../realtime-client";
import { useSession } from "../session/store";
import { appVersion, IN_TAURI } from "./platform";
import { checkUpdate, installUpdate, useUpdate } from "./updater";

export function AboutPage() {
  const { baseUrl, session } = useSession();
  const connected = useRealtime((s) => s.connected);
  const [ver, setVer] = useState("…");
  const health = useQuery({ queryKey: ["health"], queryFn: () => getJson<Health>("/api/health") });
  const up = useUpdate();

  useEffect(() => {
    void appVersion().then(setVer);
  }, []);

  return (
    <section className="about">
      <h1>Giới thiệu</h1>
      <dl>
        <dt>Ứng dụng</dt>
        <dd>Phenikaa IT Monitor Desktop <b>{ver}</b></dd>
        <dt>Máy chủ Core</dt>
        <dd>{baseUrl}</dd>
        <dt>Phiên bản Core</dt>
        <dd>{health.isPending ? "…" : health.isError ? <span className="err">{health.error.message}</span> : health.data.version}</dd>
        <dt>Kênh realtime</dt>
        <dd>{connected ? <span className="ok">Đang kết nối</span> : <span className="err">Mất kết nối</span>}</dd>
        <dt>Tổ chức · người dùng</dt>
        <dd>{session?.tenant_code} · {session?.username} ({session?.permissions.length ?? 0} quyền)</dd>
      </dl>
      <h2>Cập nhật</h2>
      {IN_TAURI ? (
        <div className="about-update">
          <button disabled={up.checking || up.installing} onClick={() => void checkUpdate()}>
            {up.checking ? "Đang kiểm tra…" : "Kiểm tra cập nhật"}
          </button>
          {up.update && !up.installing && (
            <button onClick={() => void installUpdate()}>Cài bản {up.update.version}</button>
          )}
          <p className="muted">
            {up.error
              ? `Không kiểm tra được: ${up.error}`
              : up.update
                ? `Có bản mới ${up.update.version}.`
                : up.checkedAt
                  ? `Đang dùng bản mới nhất (kiểm lúc ${up.checkedAt.toLocaleTimeString("vi-VN")}).`
                  : "Ứng dụng tự kiểm tra sau khi mở và mỗi 6 giờ."}
          </p>
        </div>
      ) : (
        <p className="muted">Đang chạy trong trình duyệt (chế độ phát triển) — không tự cập nhật.</p>
      )}
    </section>
  );
}
