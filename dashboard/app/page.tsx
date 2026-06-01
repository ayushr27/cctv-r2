"use client";

import { useEffect, useState } from "react";
import {
  getMetrics,
  getEvents,
  type Metrics,
  type EventEnvelope,
} from "../lib/api";

const POLL_MS = 5000;

function KpiCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-edge bg-panel p-5">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-2 text-3xl font-semibold text-white tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function rupees(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function clockTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return ts;
  }
}

const TYPE_COLOR: Record<string, string> = {
  "visit.entered": "text-emerald-400",
  "visit.entered_zone": "text-sky-400",
  "visit.exited_zone": "text-slate-400",
  "visit.approached_cash": "text-amber-400",
  "visit.ended": "text-slate-500",
  "track.staff_classified": "text-fuchsia-400",
};

export default function LivePage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const [m, e] = await Promise.all([getMetrics(), getEvents(undefined, 20)]);
        if (!alive) return;
        setMetrics(m);
        setEvents(e.events.slice().reverse()); // newest first
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

  return (
    <div className="space-y-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-white">Live</h1>
        <span className="flex items-center gap-2 text-xs text-slate-400">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          polling every {POLL_MS / 1000}s
        </span>
      </div>

      {error && (
        <div className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          API unreachable: {error}
        </div>
      )}

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard
          label="Footfall"
          value={metrics ? String(metrics.footfall) : "—"}
          sub="unique customers (staff excl.)"
        />
        <KpiCard
          label="Conversion"
          value={
            metrics && metrics.conversion_rate !== null
              ? (metrics.conversion_rate * 100).toFixed(1) + "%"
              : "—"
          }
          sub="bills ÷ footfall, 5-min join"
        />
        <KpiCard
          label="Avg bill value"
          value={rupees(metrics?.avg_bill_value ?? null)}
          sub={metrics ? `peak hour ${metrics.peak_hour ?? "—"}` : ""}
        />
        <KpiCard
          label="Total revenue"
          value={rupees(metrics?.total_revenue ?? null)}
          sub="POS, selected window"
        />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-slate-300">Recent events</h2>
        <div className="rounded-xl border border-edge bg-panel divide-y divide-edge max-h-[420px] overflow-y-auto">
          {events.length === 0 && (
            <div className="px-4 py-6 text-sm text-slate-500">No events yet…</div>
          )}
          {events.map((e) => (
            <div key={e.event_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
              <span className="w-20 shrink-0 tabular-nums text-slate-500">
                {clockTime(e.ts)}
              </span>
              <span
                className={`w-44 shrink-0 font-mono text-xs ${
                  TYPE_COLOR[e.type] ?? "text-slate-300"
                }`}
              >
                {e.type}
              </span>
              {e.camera && (
                <span className="rounded bg-edge px-1.5 py-0.5 text-[10px] uppercase text-slate-400">
                  {e.camera}
                </span>
              )}
              <span className="truncate text-xs text-slate-500">
                {(e.payload.zone as string) ??
                  (e.payload.visit_id as string)?.slice(0, 10) ??
                  ""}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
