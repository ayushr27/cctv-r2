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

// Bubble positions over the real store floor plan (store_layout.png, % coords).
// Zones are placed at their actual location on the plan: top wall = skincare/
// derma brands, bottom wall = colour cosmetics, F.O.H centre = makeup units,
// cash counter + accessories on the right.
const ZONE_POS: Record<string, { x: number; y: number }> = {
  the_face_shop: { x: 22, y: 11 }, // top wall, left
  dermdoc: { x: 45, y: 11 }, // top wall, centre
  makeup_unit: { x: 56, y: 48 }, // F.O.H makeup units, centre
  faces_canada: { x: 55, y: 90 }, // bottom wall
  alps_goodness: { x: 78, y: 90 }, // bottom wall, right
  cash_counter: { x: 85, y: 42 }, // right side
  accessories: { x: 83, y: 12 }, // top-right board
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

      {/* Zone heatmap over the real store floor plan */}
      <section className="rounded-xl border border-edge bg-panel p-5">
        <h2 className="mb-1 text-sm font-medium text-slate-300">
          Zone heatmap (store floor plan)
        </h2>
        <p className="mb-3 text-xs text-slate-500">
          Bubble size ∝ visits, placed on the actual Brigade Road floor plan.
          Each zone maps to the POS brands shelved there, so the table joins
          footfall to brand revenue.
        </p>
        <div className="relative w-full overflow-hidden rounded-lg border border-edge bg-white">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/store_layout.png"
            alt="store floor plan"
            className="w-full"
          />
          {zones.map((z) => {
            const pos = ZONE_POS[z.name];
            if (!pos) return null;
            const size = 22 + (z.visits / maxVisits) * 56;
            return (
              <div
                key={z.name}
                className="absolute -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
              >
                <div
                  className="flex items-center justify-center rounded-full bg-rose-500/50 ring-2 ring-rose-400 text-[11px] font-bold text-white shadow"
                  style={{ width: size, height: size }}
                  title={`${z.name}: ${z.visits} visits, avg ${z.avg_dwell_seconds}s, ₹${z.brand_revenue} brand sales`}
                >
                  {z.visits}
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
                <th className="py-2 text-right">Avg dwell (s)</th>
                <th className="py-2 text-right">Brand revenue</th>
                <th className="py-2">Brands</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-edge">
              {zones.map((z) => (
                <tr key={z.name}>
                  <td className="py-2 text-slate-200">{z.name}</td>
                  <td className="py-2 text-right tabular-nums">{z.visits}</td>
                  <td className="py-2 text-right tabular-nums">
                    {z.avg_dwell_seconds}
                  </td>
                  <td className="py-2 text-right tabular-nums text-emerald-300">
                    ₹{z.brand_revenue.toLocaleString("en-IN")}
                  </td>
                  <td className="py-2 text-xs text-slate-500">
                    {z.brands.slice(0, 3).join(", ")}
                    {z.brands.length > 3 ? "…" : ""}
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
