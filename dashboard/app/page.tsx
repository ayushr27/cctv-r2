"use client";

import { useEffect, useState } from "react";
import { getMetrics, getEvents, type Metrics, type EventEnvelope } from "../lib/api";
import { Card, PageHeader, StatCard, Skeleton, ErrorBanner, cx } from "../components/ui";

const POLL_MS = 5000;

function rupees(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

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
  "visit.entered": "text-emerald-400",
  "visit.entered_zone": "text-accent-hover",
  "visit.exited_zone": "text-slate-400",
  "visit.approached_cash": "text-amber-400",
  "visit.ended": "text-slate-500",
  "track.staff_classified": "text-fuchsia-400",
};

export default function LivePage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [m, e] = await Promise.all([getMetrics(), getEvents(undefined, 20)]);
        if (!alive) return;
        setMetrics(m);
        setEvents(e.events.slice().reverse());
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
  }, []);

  const conv = metrics && metrics.conversion_rate !== null
    ? (metrics.conversion_rate * 100).toFixed(1) + "%" : "—";

  return (
    <div className="space-y-8">
      <PageHeader
        title="Live overview"
        subtitle="Real-time store KPIs from CCTV footfall joined to POS sales."
      />

      {error && <ErrorBanner message={error} />}

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard loading={loading} label="Footfall" value={metrics?.footfall}
          sub="unique customers · staff excluded" />
        <StatCard loading={loading} label="Conversion" value={conv}
          sub="bills ÷ footfall · 5-min join" />
        <StatCard loading={loading} label="Avg bill value" value={rupees(metrics?.avg_bill_value ?? null)}
          sub={`peak hour ${metrics?.peak_hour ?? "—"}`} />
        <StatCard loading={loading} label="Total revenue" value={rupees(metrics?.total_revenue ?? null)}
          sub="POS · selected window" emphasis />
      </section>

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard loading={loading} label="Store employees" value={metrics?.staff_count}
          sub="detected · black uniform / behaviour" />
        <StatCard loading={loading} label="Unique groups" value={metrics?.unique_groups}
          sub="distinct shopping parties" />
        <StatCard loading={loading} label="Peak hour" value={metrics?.peak_hour ?? "—"}
          sub="busiest entry hour (IST)" />
        <StatCard loading={loading} label="Avg dwell" value={metrics ? `${metrics.avg_dwell_seconds}s` : undefined}
          sub="mean visit · staff excluded" />
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-300">Recent events</h2>
          <span className="text-xs text-slate-500">last {events.length}</span>
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
          {!loading && events.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-slate-500">No events in window.</div>
          )}
          {!loading &&
            events.map((e) => (
              <div key={e.event_id}
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
                <span className="truncate text-xs text-slate-500">
                  {(e.payload.zone as string) ?? (e.payload.visit_id as string)?.slice(0, 10) ?? ""}
                </span>
              </div>
            ))}
        </Card>
      </section>
    </div>
  );
}
