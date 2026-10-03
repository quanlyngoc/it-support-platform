// Biểu đồ online / offline theo phòng (Sổ tay 4.6 — Chart.js). Chỉ nạp đúng thành phần cột để gói nhỏ. Biểu đồ tạo MỘT
// lần, dữ liệu mới chỉ cập nhật tại chỗ, không hiệu ứng → số nhảy theo realtime mà không giật.
import { useEffect, useRef } from "react";
import { BarController, BarElement, CategoryScale, Chart, Legend, LinearScale, Tooltip } from "chart.js";
import type { Room } from "../api-client/types";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const shortName = (n: string) => n.match(/\d{3}/)?.[0] ?? n; // "Phòng 301 - A6" → "301"

export function OnlineChart({ rooms }: { rooms: Room[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const chart = useRef<Chart<"bar"> | null>(null);

  useEffect(() => {
    if (!canvas.current) return;
    const ink = css("--muted");
    const grid = css("--line");
    chart.current = new Chart(canvas.current, {
      type: "bar",
      data: {
        labels: [],
        datasets: [
          { label: "Online", data: [], backgroundColor: css("--ok"), stack: "s", maxBarThickness: 56 },
          { label: "Offline", data: [], backgroundColor: css("--surface-2"), borderColor: grid, borderWidth: 1,
            stack: "s", maxBarThickness: 56 },
        ],
      },
      options: {
        animation: false,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: ink } }, tooltip: { mode: "index", intersect: false } },
        scales: {
          x: { stacked: true, ticks: { color: ink }, grid: { display: false } },
          y: { stacked: true, beginAtZero: true, ticks: { color: ink, precision: 0 }, grid: { color: grid } },
        },
      },
    });
    return () => {
      chart.current?.destroy();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    c.data.labels = rooms.map((r) => shortName(r.name));
    c.data.datasets[0].data = rooms.map((r) => r.online);
    c.data.datasets[1].data = rooms.map((r) => r.total - r.online);
    c.update("none");
  }, [rooms]);

  return (
    <div className="chart" role="img" aria-label="Biểu đồ số máy online và offline theo phòng">
      <canvas ref={canvas} />
    </div>
  );
}
