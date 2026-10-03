import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import { router } from "./router";
import { useSession } from "./session/store";
import "./shared/app.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } } });

function Root() {
  const ready = useSession((s) => s.ready);
  React.useEffect(() => {
    void useSession.getState().hydrate();
  }, []);
  if (!ready) return null; // đợi đọc phiên đã lưu, tránh nháy màn đăng nhập rồi mới vào
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
