// Biểu đồ cột "số giờ sử dụng" (Chart.js — cùng bộ thành phần đã đăng ký ở OnlineChart). Tạo một lần, dữ liệu đổi thì
// cập nhật tại chỗ, không hiệu ứng.
import { useEffect, useRef } from "react";
import { BarController, BarElement, CategoryScale, Chart, LinearScale, Tooltip } from "chart.js";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function HoursChart({ labels, hours, label = "Giờ sử dụng", onPick }: {
  labels: string[]; hours: number[]; label?: string; onPick?: (index: number) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const chart = useRef<Chart<"bar"> | null>(null);
  const pick = useRef(onPick);
  useEffect(() => {
    pick.current = onPick;
  });

  useEffect(() => {
    if (!canvas.current) return;
    const ink = css("--muted");
    chart.current = new Chart(canvas.current, {
      type: "bar",
      data: { labels: [], datasets: [{ label, data: [], backgroundColor: css("--accent"), maxBarThickness: 48 }] },
      options: {
        animation: false,
        maintainAspectRatio: false,
        onClick: (_e, els) => {
          if (els.length && pick.current) pick.current(els[0].index);
        },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.formattedValue} giờ` } } },
        scales: {
          x: { ticks: { color: ink }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: ink }, grid: { color: css("--line") },
               title: { display: true, text: "Giờ", color: ink } },
        },
      },
    });
    return () => {
      chart.current?.destroy();
      chart.current = null;
    };
  }, []); // nhãn cố định theo chỗ dùng — dựng một lần

  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    c.data.labels = labels;
    c.data.datasets[0].data = hours;
    c.update("none");
  }, [labels, hours]);

  return (
    <div className="chart" role="img" aria-label={`Biểu đồ ${label.toLowerCase()}`}>
      <canvas ref={canvas} />
    </div>
  );
}
