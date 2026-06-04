"use client";

import { useEffect, useState } from "react";
import {
  getStoreFunnel, getStoreHeatmap, storeLabel,
  type StoreFunnel, type StoreHeatmap,
} from "../../lib/api";
import { useStore } from "../../components/StoreContext";
import { Card, PageHeader, Skeleton, ErrorBanner, Bar } from "../../components/ui";

const POLL_MS = 5000;

// Per-store floor-plan + bubble positions, keyed by canonical zone_id (positions
// are % of the layout image, hand-calibrated to the provided plans in
// resources/Store {1,2}). A store with no entry here (or the cumulative ALL view,
// whose zones span both plans) falls back to the bar heatmap below.
type Layout = { img: string; aspect: string; zones: Record<string, { x: number; y: number }> };
const STORE_LAYOUTS: Record<string, Layout> = {
  STORE_BLR_002: {
    img: "/store_layout.png",
    aspect: "940 / 451",
    zones: {
      the_face_shop: { x: 22, y: 11 },
      dermdoc: { x: 45, y: 11 },
      makeup_unit: { x: 56, y: 48 },
      faces_canada: { x: 55, y: 90 },
      alps_goodness: { x: 78, y: 90 },
      cash_counter: { x: 85, y: 42 },
      accessories: { x: 83, y: 12 },
    },
  },
  STORE_BLR_009: {
    img: "/store2_layout.png",
    aspect: "960 / 1210", // portrait plan: entrance bottom, cash counter top
    zones: {
      cash_counter: { x: 47, y: 27 },
      right_wall: { x: 90, y: 46 },
      left_wall: { x: 9, y: 46 },
    },
  },
};

export default function FunnelPage() {
  const { store } = useStore();
  const [funnel, setFunnel] = useState<StoreFunnel | null>(null);
  const [heat, setHeat] = useState<StoreHeatmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const tick = async () => {
      try {
        const [f, h] = await Promise.all([getStoreFunnel(store), getStoreHeatmap(store)]);
        if (!alive) return;
        setFunnel(f); setHeat(h); setError(null);
      } catch (err) {
        if (alive) setError(String(err));
      } finally {
        if (alive) setLoading(false);
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, [store]);

  const stages = funnel?.stages ?? [];
  const maxStage = Math.max(1, ...stages.map((s) => s.count));
  const zones = heat?.zones ?? [];
  const maxVisits = Math.max(1, ...zones.map((z) => z.visits));
  const layout = STORE_LAYOUTS[store];
  const hasFloorplan = !!layout && zones.some((z) => layout.zones[z.zone_id]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Conversion funnel & zones"
        subtitle={`Entry → Zone → Billing → Purchase, and per-zone engagement — ${storeLabel(store)}.`}
      />

      {error && <ErrorBanner message={error} />}

      <Card className="p-6">
        <h2 className="mb-5 text-sm font-medium text-slate-300">Conversion funnel</h2>
        {loading ? (
          <Skeleton className="h-48 w-full" />
        ) : maxStage <= 1 && stages.every((s) => s.count === 0) ? (
          <p className="py-8 text-center text-sm text-slate-500">
            No funnel data in this window
            {store === "STORE_BLR_009" && " — run the Store 2 detection pipeline to populate"}.
          </p>
        ) : (
          <div className="space-y-3">
            {stages.map((s, i) => {
              const w = Math.max(8, (s.count / maxStage) * 100);
              return (
                <div key={s.stage}>
                  <div className="mb-1 flex items-baseline justify-between text-xs">
                    <span className="font-medium capitalize text-slate-200">
                      {s.stage.replace(/_/g, " ")}
                    </span>
                    <span className="tabular-nums text-slate-400">
                      {s.count}
                      {i > 0 && s.drop_off > 0 && (
                        <span className="ml-2 text-red-400">−{(s.drop_off * 100).toFixed(0)}%</span>
                      )}
                    </span>
                  </div>
                  <div className="flex justify-center">
                    <div
                      className="flex h-10 items-center justify-center rounded-lg bg-gradient-to-b from-accent/80 to-accent text-sm font-semibold text-white shadow-pop transition-all duration-500"
                      style={{ width: `${w}%` }}
                    >
                      {w > 12 && s.count}
                    </div>
                  </div>
                </div>
              );
            })}
            <p className="pt-2 text-center text-[11px] text-slate-500">
              {funnel?.sessions} sessions · staff excluded · re-entries de-duplicated
              {funnel?.data_confidence === "low" && " · low confidence (small sample)"}
            </p>
          </div>
        )}
      </Card>

      <Card className="p-6">
        <h2 className="text-sm font-medium text-slate-300">Zone heatmap</h2>
        <p className="mb-4 mt-1 text-xs text-slate-500">
          {hasFloorplan
            ? "Bubble size ∝ visits, placed on the real store floor plan."
            : "Visit intensity per zone (staff excluded)."}
        </p>
        {loading ? (
          <div className="w-full" style={{ aspectRatio: layout?.aspect ?? "940 / 451" }}>
            <Skeleton className="h-full w-full" />
          </div>
        ) : zones.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-500">No zone activity in this window.</p>
        ) : hasFloorplan ? (
          <div className="relative w-full overflow-hidden rounded-lg border border-border">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={layout!.img} alt="store floor plan" className="w-full" />
            {zones.map((z) => {
              const pos = layout!.zones[z.zone_id];
              if (!pos) return null;
              const size = 22 + (z.visits / maxVisits) * 52;
              const opacity = 0.35 + (z.visits / maxVisits) * 0.5;
              return (
                <div key={z.zone_id} className="absolute -translate-x-1/2 -translate-y-1/2"
                  style={{ left: `${pos.x}%`, top: `${pos.y}%` }}>
                  <div className="flex items-center justify-center rounded-full text-[11px] font-semibold text-white ring-2 ring-accent-hover transition-transform hover:scale-110"
                    style={{ width: size, height: size, background: `rgba(99,102,241,${opacity})` }}
                    title={`${z.zone_id}: ${z.visits} visits · avg ${(z.avg_dwell_ms / 1000).toFixed(0)}s`}>
                    {z.visits}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="space-y-3">
            {zones.map((z) => (
              <div key={z.zone_id}>
                <div className="mb-1 flex justify-between text-xs">
                  <span className="text-slate-300">{z.zone_id}</span>
                  <span className="tabular-nums text-slate-400">
                    {z.visits} visits · {(z.avg_dwell_ms / 1000).toFixed(0)}s avg
                  </span>
                </div>
                <Bar value={z.visit_score} max={100} tone="success" />
              </div>
            ))}
          </div>
        )}

        {zones.length > 0 && (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="pb-2 font-medium">Zone</th>
                  <th className="pb-2 text-right font-medium">Visits</th>
                  <th className="pb-2 text-right font-medium">Avg dwell</th>
                  <th className="pb-2 text-right font-medium">Intensity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {zones.map((z) => (
                  <tr key={z.zone_id} className="transition-colors hover:bg-elevated/50">
                    <td className="py-2.5 font-medium text-slate-200">{z.zone_id}</td>
                    <td className="py-2.5 text-right tabular-nums text-slate-300">{z.visits}</td>
                    <td className="py-2.5 text-right tabular-nums text-slate-400">
                      {(z.avg_dwell_ms / 1000).toFixed(0)}s
                    </td>
                    <td className="py-2.5 text-right tabular-nums text-emerald-300">
                      {z.visit_score.toFixed(0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
