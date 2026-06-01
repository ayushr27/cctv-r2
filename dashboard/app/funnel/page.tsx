"use client";

import { useEffect, useState } from "react";
import {
  FunnelChart,
  Funnel as RFunnel,
  LabelList,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  getFunnel,
  getZones,
  type Funnel,
  type Zone,
} from "../../lib/api";

const POLL_MS = 5000;
const STAGE_COLORS = ["#34d399", "#38bdf8", "#a78bfa", "#fbbf24", "#fb7185"];

// Illustrative positions for zone bubbles over the CCTV frame. Zones live in
// per-camera pixel space (cam1/cam2 interior); the backdrop is the cam5 frame,
// so these positions are layout hints, not exact projections — sizing is the
// real signal (proportional to visit count).
const ZONE_POS: Record<string, { x: number; y: number }> = {
  center_aisle: { x: 50, y: 38 },
  left_counter: { x: 20, y: 55 },
  makeup_wall: { x: 78, y: 45 },
  right_display: { x: 85, y: 70 },
  left_shelf: { x: 15, y: 30 },
  skincare: { x: 35, y: 25 },
  cash_counter: { x: 45, y: 78 },
};

export default function FunnelPage() {
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [f, z] = await Promise.all([getFunnel(), getZones()]);
        if (!alive) return;
        setFunnel(f);
        setZones(z.zones);
        setError(null);
      } catch (err) {
        if (alive) setError(String(err));
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const chartData =
    funnel?.stages.map((s, i) => ({
      name: s.name,
      value: s.count,
      fill: STAGE_COLORS[i % STAGE_COLORS.length],
    })) ?? [];

  const maxVisits = Math.max(1, ...zones.map((z) => z.visits));

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold text-white">Funnel & Zones</h1>

      {error && (
        <div className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          API unreachable: {error}
        </div>
      )}

      {/* Funnel */}
      <section className="rounded-xl border border-edge bg-panel p-5">
        <h2 className="mb-3 text-sm font-medium text-slate-300">
          Conversion funnel
        </h2>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <FunnelChart>
              <Tooltip
                contentStyle={{ background: "#141a2a", border: "1px solid #222b40" }}
              />
              <RFunnel dataKey="value" data={chartData} isAnimationActive>
                <LabelList
                  position="right"
                  fill="#e2e8f0"
                  stroke="none"
                  dataKey="name"
                />
                <LabelList
                  position="left"
                  fill="#94a3b8"
                  stroke="none"
                  dataKey="value"
                />
                {chartData.map((d, i) => (
                  <Cell key={i} fill={d.fill} />
                ))}
              </RFunnel>
            </FunnelChart>
          </ResponsiveContainer>
        </div>
        {funnel && (
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-400">
            {funnel.drop_off_rates.map((d, i) => (
              <span key={i}>
                {funnel.stages[i].name} → {funnel.stages[i + 1].name}:{" "}
                <span className={d < 0 ? "text-amber-400" : "text-slate-300"}>
                  {(d * 100).toFixed(1)}% drop
                </span>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* Zone heatmap */}
      <section className="rounded-xl border border-edge bg-panel p-5">
        <h2 className="mb-1 text-sm font-medium text-slate-300">Zone heatmap</h2>
        <p className="mb-3 text-xs text-slate-500">
          Bubble size ∝ visits. Backdrop is a real CAM 5 frame; positions are
          illustrative (zones are per-camera).
        </p>
        <div className="relative w-full overflow-hidden rounded-lg border border-edge">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/store_frame.jpg"
            alt="store CCTV frame"
            className="w-full opacity-60"
          />
          {zones.map((z) => {
            const pos = ZONE_POS[z.name] ?? { x: 50, y: 50 };
            const size = 24 + (z.visits / maxVisits) * 64;
            return (
              <div
                key={z.name}
                className="absolute -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
              >
                <div
                  className="flex items-center justify-center rounded-full bg-sky-400/30 ring-2 ring-sky-300 text-[10px] font-semibold text-white"
                  style={{ width: size, height: size }}
                  title={`${z.name}: ${z.visits} visits, avg ${z.avg_dwell_seconds}s`}
                >
                  {z.visits}
                </div>
                <div className="mt-1 text-center text-[10px] text-slate-300 whitespace-nowrap">
                  {z.name}
                </div>
              </div>
            );
          })}
        </div>

        {/* Zone table */}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2">Zone</th>
                <th className="py-2 text-right">Visits</th>
                <th className="py-2 text-right">Total dwell (s)</th>
                <th className="py-2 text-right">Avg dwell (s)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-edge">
              {zones.map((z) => (
                <tr key={z.name}>
                  <td className="py-2 text-slate-200">{z.name}</td>
                  <td className="py-2 text-right tabular-nums">{z.visits}</td>
                  <td className="py-2 text-right tabular-nums">
                    {z.total_dwell_seconds}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {z.avg_dwell_seconds}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
