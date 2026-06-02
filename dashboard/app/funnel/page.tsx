"use client";

import { useEffect, useState } from "react";
import {
  FunnelChart, Funnel as RFunnel, LabelList, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { getFunnel, getZones, type Funnel, type Zone } from "../../lib/api";
import { Card, PageHeader, Badge, Skeleton, ErrorBanner } from "../../components/ui";

const POLL_MS = 5000;
// single-hue indigo scale — restrained, professional
const STAGE_SHADES = ["#a5b4fc", "#818cf8", "#6366f1", "#4f46e5", "#4338ca"];

const ZONE_POS: Record<string, { x: number; y: number }> = {
  the_face_shop: { x: 22, y: 11 },
  dermdoc: { x: 45, y: 11 },
  makeup_unit: { x: 56, y: 48 },
  faces_canada: { x: 55, y: 90 },
  alps_goodness: { x: 78, y: 90 },
  cash_counter: { x: 85, y: 42 },
  accessories: { x: 83, y: 12 },
};

export default function FunnelPage() {
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [f, z] = await Promise.all([getFunnel(), getZones()]);
        if (!alive) return;
        setFunnel(f); setZones(z.zones); setError(null);
      } catch (err) {
        if (alive) setError(String(err));
      } finally {
        if (alive) setLoading(false);
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const chartData = funnel?.stages.map((s, i) => ({
    name: s.name, value: s.count, fill: STAGE_SHADES[i % STAGE_SHADES.length],
  })) ?? [];
  const maxVisits = Math.max(1, ...zones.map((z) => z.visits));

  return (
    <div className="space-y-8">
      <PageHeader title="Conversion funnel & zones"
        subtitle="Five-stage funnel and per-zone engagement on the store floor plan." />

      {error && <ErrorBanner message={error} />}

      <Card className="p-6">
        <h2 className="mb-4 text-sm font-medium text-slate-300">Conversion funnel</h2>
        {loading ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <FunnelChart>
                  <Tooltip contentStyle={{ background: "#161a24", border: "1px solid #2d3344", borderRadius: 10, fontSize: 12 }}
                    itemStyle={{ color: "#e2e8f0" }} labelStyle={{ color: "#94a3b8" }} />
                  <RFunnel dataKey="value" data={chartData} isAnimationActive>
                    <LabelList position="right" fill="#cbd5e1" stroke="none" dataKey="name" className="text-xs" />
                    <LabelList position="left" fill="#64748b" stroke="none" dataKey="value" />
                    {chartData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                  </RFunnel>
                </FunnelChart>
              </ResponsiveContainer>
            </div>
            {funnel && (
              <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
                {funnel.drop_off_rates.map((d, i) => (
                  <Badge key={i} tone={d < 0 ? "warning" : "neutral"}>
                    {funnel.stages[i].name} → {funnel.stages[i + 1].name}: {(d * 100).toFixed(1)}%
                  </Badge>
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      <Card className="p-6">
        <h2 className="text-sm font-medium text-slate-300">Zone heatmap</h2>
        <p className="mb-4 mt-1 text-xs text-slate-500">
          Bubble size ∝ visits, placed on the real Brigade Road floor plan. Each zone maps to
          the POS brands shelved there.
        </p>
        {loading ? (
          <Skeleton className="aspect-[940/451] w-full" />
        ) : (
          <div className="relative w-full overflow-hidden rounded-lg border border-border">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/store_layout.png" alt="store floor plan" className="w-full" />
            {zones.map((z) => {
              const pos = ZONE_POS[z.name];
              if (!pos) return null;
              const size = 22 + (z.visits / maxVisits) * 52;
              const opacity = 0.35 + (z.visits / maxVisits) * 0.5;
              return (
                <div key={z.name} className="absolute -translate-x-1/2 -translate-y-1/2"
                  style={{ left: `${pos.x}%`, top: `${pos.y}%` }}>
                  <div className="flex items-center justify-center rounded-full text-[11px] font-semibold text-white ring-2 ring-accent-hover transition-transform hover:scale-110"
                    style={{ width: size, height: size, background: `rgba(99,102,241,${opacity})` }}
                    title={`${z.name}: ${z.visits} visits · avg ${z.avg_dwell_seconds}s · ₹${z.brand_revenue}`}>
                    {z.visits}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2 font-medium">Zone</th>
                <th className="pb-2 text-right font-medium">Visits</th>
                <th className="pb-2 text-right font-medium">Avg dwell</th>
                <th className="pb-2 text-right font-medium">Brand revenue</th>
                <th className="pb-2 pl-4 font-medium">Brands</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading
                ? Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i}><td colSpan={5} className="py-3"><Skeleton className="h-3 w-full" /></td></tr>
                  ))
                : zones.map((z) => (
                    <tr key={z.name} className="transition-colors hover:bg-elevated/50">
                      <td className="py-2.5 font-medium text-slate-200">{z.name}</td>
                      <td className="py-2.5 text-right tabular-nums text-slate-300">{z.visits}</td>
                      <td className="py-2.5 text-right tabular-nums text-slate-400">{z.avg_dwell_seconds}s</td>
                      <td className="py-2.5 text-right tabular-nums text-emerald-300">
                        ₹{z.brand_revenue.toLocaleString("en-IN")}
                      </td>
                      <td className="py-2.5 pl-4 text-xs text-slate-500">
                        {z.brands.slice(0, 3).join(", ")}{z.brands.length > 3 ? "…" : ""}
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
