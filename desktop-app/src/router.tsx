// createHashRouter: đường dẫn dạng #/rooms/<id> → tải lại cửa sổ (F5) vẫn đúng trang mà không cần máy chủ web
// (Sổ tay 4.3 — Tauri phục vụ tệp tĩnh, không có máy chủ Node để trả index.html cho mọi đường dẫn).
import { createHashRouter } from "react-router";
import { LoginPage } from "./authentication/LoginPage";
import { DashboardPage } from "./dashboard/DashboardPage";
import { DevicePage } from "./devices/DevicePage";
import { RoomPage } from "./rooms/RoomPage";
import { RoomsPage } from "./rooms/RoomsPage";
import { AboutPage } from "./shared/AboutPage";
import { Layout } from "./shared/Layout";

export const router = createHashRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "rooms", element: <RoomsPage /> },
      { path: "rooms/:id", element: <RoomPage /> },
      { path: "devices/:id", element: <DevicePage /> },
      { path: "about", element: <AboutPage /> },
    ],
  },
]);
