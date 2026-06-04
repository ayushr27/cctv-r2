"use client";

import { useEffect, useState } from "react";
import { getStoreLive, storeLabel, type StoreLive } from "../lib/api";
import { useStore } from "../components/StoreContext";
import {
  Card, PageHeader, StatCard, NoDataStat, DemographicsPanel, Skeleton, ErrorBanner, cx,
} from "../components/ui";

const POLL_MS = 5000;

const rupees = (n?: number | null) =>
  n == null ? "—" : "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });

function clock(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString("en-IN", {
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  } catch {
    return ts;
  }
}

const TYPE_TONE: Record<string, string> = {
  ENTRY: "text-emerald-400",
  REENTRY: "text-emerald-300",
  ZONE_ENTER: "text-accent-hover",
  ZONE_EXIT: "text-slate-400",
  ZONE_DWELL: "text-sky-400",
  BILLING_QUEUE_JOIN: "text-amber-400",
  BILLING_QUEUE_ABANDON: "text-red-400",
  EXIT: "text-slate-500",
};

export default function LivePage() {
  const { store } = useStore();
  const [d, setD] = useState<StoreLive | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const tick = async () => {
      try {
        const r = await getStoreLive(store);
        if (!alive) return;
        setD(r);
        setError(null);
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

  const conv = d ? (d.conversion_rate * 100).toFixed(1) + "%" : "—";
  const dwell = d ? (d.avg_dwell_ms / 1000).toFixed(1) + "s" : undefined;
  const noPos = store === "STORE_BLR_009" || d?.has_pos === false;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Live overview"
        subtitle={`Real-time KPIs — ${storeLabel(store)}. CCTV footfall (sample clip) joined to POS sales (full trading day).`}
      />

      {error && <ErrorBanner message={error} />}

      {d && d.data_confidence === "low" && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-300">
          Low data confidence — small sample in this window; numbers are directional.
          {noPos && " Store 2 has no POS export, so revenue & rupee conversion are unavailable (CV checkout rate shown instead)."}
        </div>
      )}

      {/* Footfall = two co-headline numbers (peak occupancy + total visitors). */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard loading={loading} label="Peak occupancy" value={d?.peak_occupancy}
          sub="people on the busiest camera at once" emphasis />
        <StatCard loading={loading} label="Total visitors" value={d?.total_visitors}
          sub={d ? `de-fragmented · ${d.door_entries} door entries · staff excl.` : undefined} emphasis />
        <StatCard loading={loading} label="Conversion" value={conv}
          sub={d ? (d.has_pos ? "billing ÷ visitors (POS-matched)" : `${d.observed_checkouts ?? 0} checkouts ÷ visitors (CV)`) : undefined} />
        {noPos ? (
          <StatCard loading={loading} label="Checkouts seen" value={d?.observed_checkouts ?? "—"}
            sub="on the billing camera (CV)" />
        ) : (
          <StatCard loading={loading} label="Total revenue" value={rupees(d?.total_revenue)}
            sub="POS · full trading day" emphasis />
        )}
      </section>

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard loading={loading} label="Store employees" value={d?.staff_count}
          sub="detected · uniform / behaviour" />
        <StatCard loading={loading} label="Avg dwell" value={dwell}
          sub="mean zone dwell · staff excl." />
        <StatCard loading={loading} label="Peak hour" value={d?.peak_hour ?? "—"}
          sub="busiest entry hour (IST)" />
        {noPos ? (
          <NoDataStat label="Avg bill value" reason="no POS feed for Store 2" />
        ) : (
          <StatCard loading={loading} label="Avg bill value" value={rupees(d?.avg_bill_value)}
            sub="POS · full trading day" />
        )}
      </section>

      <DemographicsPanel
        gender={d?.demographics.gender ?? {}}
        age={d?.demographics.age_bucket ?? {}}
        note={d?.demographics.note}
        loading={loading}
      />

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-300">Recent events</h2>
          <span className="text-xs text-slate-500">last {d?.recent_events.length ?? 0}</span>
        </div>
        <Card className="divide-y divide-border overflow-hidden">
          {loading &&
            Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-3 w-40" />
                <Skeleton className="ml-auto h-3 w-20" />
              </div>
            ))}
          {!loading && (d?.recent_events.length ?? 0) === 0 && (
            <div className="px-4 py-8 text-center text-sm text-slate-500">
              No events in this window {store === "STORE_BLR_009" && "— run the Store 2 detection pipeline to populate"}.
            </div>
          )}
          {!loading &&
            d?.recent_events.map((e, i) => (
              <div key={i}
                className="flex items-center gap-4 px-4 py-2.5 text-sm transition-colors hover:bg-elevated/60">
                <span className="w-16 shrink-0 tabular-nums text-xs text-slate-500">{clock(e.ts)}</span>
                <span className={cx("w-48 shrink-0 font-mono text-xs", TYPE_TONE[e.type] ?? "text-slate-300")}>
                  {e.type}
                </span>
                {e.camera && (
                  <span className="rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                    {e.camera}
                  </span>
                )}
                {store === "ALL" && (
                  <span className="rounded border border-border bg-elevated px-1.5 py-0.5 text-[10px] text-slate-500">
                    {e.store_id === "STORE_BLR_002" ? "S1" : "S2"}
                  </span>
                )}
                <span className="truncate text-xs text-slate-500">{e.zone ?? e.visitor.slice(0, 10)}</span>
              </div>
            ))}
        </Card>
      </section>
    </div>
  );
}
