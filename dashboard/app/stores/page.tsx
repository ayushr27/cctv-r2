"use client";

import { useEffect, useState } from "react";
import {
  getStoreMetrics,
  getStoreFunnel,
  getStoreHeatmap,
  getStoreAnomalies,
  storeLabel,
  type StoreMetrics,
  type StoreFunnel,
  type StoreHeatmap,
  type StoreAnomaliesResponse,
} from "../../lib/api";
import { useStore } from "../../components/StoreContext";
import {
  PageHeader, Card, Badge, Bar, StatCard, DemographicsPanel, Skeleton, ErrorBanner, EmptyState,
} from "../../components/ui";

const POLL_MS = 5000;

const SEV: Record<string, "info" | "warning" | "danger"> = {
  INFO: "info", WARN: "warning", CRITICAL: "danger",
};

function pct(x: number) {
  return `${(x * 100).toFixed(0)}%`;
}

export default function StoresPage() {
  const { store } = useStore();
  const [m, setM] = useState<StoreMetrics | null>(null);
  const [f, setF] = useState<StoreFunnel | null>(null);
  const [h, setH] = useState<StoreHeatmap | null>(null);
  const [a, setA] = useState<StoreAnomaliesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const tick = async () => {
      try {
        const [mm, ff, hh, aa] = await Promise.all([
          getStoreMetrics(store), getStoreFunnel(store),
          getStoreHeatmap(store), getStoreAnomalies(store),
        ]);
        if (!alive) return;
        setM(mm); setF(ff); setH(hh); setA(aa); setError(null);
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

  const maxStage = f ? Math.max(...f.stages.map((s) => s.count), 1) : 1;
  const cvConversion = m?.observed_checkouts != null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Stores"
        subtitle={`Live PDF-contract metrics — ${storeLabel(store)} (POST /events/ingest → GET /stores/{id}/*).`}
      />

      {error && <ErrorBanner message={error} />}

      {m && m.data_confidence === "low" && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-300">
          Low data confidence — fewer than 20 sessions in this window. Numbers are
          directional. {store === "STORE_BLR_009" && "Store 2 has no POS export, so conversion is a CV checkout rate (no rupee sales)."}
        </div>
      )}

      {/* KPI cards — peak occupancy + total visitors are the two footfall headlines */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Peak occupancy" value={m?.peak_occupancy} loading={loading}
          sub="busiest camera, at once" emphasis />
        <StatCard label="Total visitors" value={m?.total_visitors} loading={loading}
          sub={m ? `de-fragmented · ${m.door_entries} door · ${m.staff_excluded} staff excl.` : undefined} emphasis />
        <StatCard label="Conversion" value={m ? pct(m.conversion_rate) : undefined} loading={loading}
          sub={m ? (cvConversion ? `${m.observed_checkouts} checkouts (CV, no POS)` : `${m.converted_visitors} converted (POS)`) : undefined} />
        <StatCard label="Abandonment" value={m ? pct(m.abandonment_rate) : undefined} loading={loading}
          sub={m ? `${m.billing_queue_abandons} of ${m.billing_queue_joins} left queue` : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Funnel */}
        <Card className="p-5">
          <div className="mb-4 text-sm font-medium text-white">Conversion funnel</div>
          {loading && <Skeleton className="h-32 w-full" />}
          {f && f.stages.map((s) => (
            <div key={s.stage} className="mb-3">
              <div className="mb-1 flex justify-between text-xs">
                <span className="capitalize text-slate-300">{s.stage.replace("_", " ")}</span>
                <span className="tabular-nums text-slate-400">
                  {s.count}{s.drop_off > 0 && <span className="ml-2 text-red-400">−{pct(s.drop_off)}</span>}
                </span>
              </div>
              <Bar value={s.count} max={maxStage} />
            </div>
          ))}
        </Card>

        {/* Heatmap */}
        <Card className="p-5">
          <div className="mb-4 text-sm font-medium text-white">Zone heatmap (visit intensity)</div>
          {loading && <Skeleton className="h-32 w-full" />}
          {h && h.zones.length === 0 && !loading && (
            <p className="text-xs text-slate-500">No zone activity in this window.</p>
          )}
          {h && h.zones.map((z) => (
            <div key={z.zone_id} className="mb-3">
              <div className="mb-1 flex justify-between text-xs">
                <span className="text-slate-300">{z.zone_id}</span>
                <span className="tabular-nums text-slate-400">
                  {z.visits} visits · {(z.avg_dwell_ms / 1000).toFixed(0)}s avg
                </span>
              </div>
              <Bar value={z.visit_score} max={100} tone="success" />
            </div>
          ))}
        </Card>
      </div>

      {/* Demographics (best-effort) */}
      <DemographicsPanel
        gender={m?.demographics.gender ?? {}}
        age={m?.demographics.age_bucket ?? {}}
        note={m?.demographics.note}
        loading={loading}
      />

      {/* Anomalies */}
      <Card className="p-5">
        <div className="mb-4 text-sm font-medium text-white">Active anomalies</div>
        {loading && <Skeleton className="h-16 w-full" />}
        {a && a.anomalies.length === 0 && !loading && (
          <EmptyState>No active anomalies for this store/window.</EmptyState>
        )}
        <div className="space-y-2">
          {a && a.anomalies.map((x, i) => (
            <div key={`${x.type}-${i}`} className="rounded-lg border border-border bg-bg p-3">
              <div className="flex items-center gap-2">
                <Badge tone={SEV[x.severity] ?? "neutral"}>{x.severity}</Badge>
                <span className="font-mono text-xs text-slate-400">{x.type}</span>
                {x.zone_id && <span className="text-xs text-slate-500">{x.zone_id}</span>}
              </div>
              <div className="mt-1.5 text-sm text-slate-300">{x.evidence}</div>
              <div className="mt-1 text-xs text-accent-hover">→ {x.suggested_action}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
