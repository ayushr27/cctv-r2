"use client";

import { useEffect, useState } from "react";
import { getAnomalies, type Anomaly } from "../../lib/api";

const POLL_MS = 5000;

const SEV_STYLE: Record<string, { dot: string; chip: string; label: string }> = {
  critical: { dot: "bg-red-500", chip: "bg-red-950 text-red-300 border-red-800", label: "Critical" },
  warning: { dot: "bg-amber-400", chip: "bg-amber-950 text-amber-300 border-amber-800", label: "Warning" },
  info: { dot: "bg-sky-400", chip: "bg-sky-950 text-sky-300 border-sky-800", label: "Info" },
};

function hourOf(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return ts;
  }
}

function AnomalyItem({ a }: { a: Anomaly }) {
  const [open, setOpen] = useState(false);
  const sev = SEV_STYLE[a.severity] ?? SEV_STYLE.info;
  return (
    <div className="relative pl-8">
      <span className={`absolute left-2 top-2 h-3 w-3 rounded-full ${sev.dot} ring-4 ring-ink`} />
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full rounded-lg border border-edge bg-panel px-4 py-3 text-left hover:border-slate-500 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase ${sev.chip}`}>
            {sev.label}
          </span>
          <span className="font-mono text-xs text-slate-400">{a.kind}</span>
          <span className="ml-auto text-xs tabular-nums text-slate-500">
            {hourOf(a.window.from)}
          </span>
        </div>
        <div className="mt-1.5 text-sm text-slate-200">{a.evidence}</div>
        {open && (
          <pre className="mt-3 overflow-x-auto rounded bg-ink p-3 text-[11px] text-slate-400">
{JSON.stringify(a, null, 2)}
          </pre>
        )}
      </button>
    </div>
  );
}

export default function AnomaliesPage() {
  const [anoms, setAnoms] = useState<Anomaly[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getAnomalies();
        if (!alive) return;
        setAnoms(r.anomalies);
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

  // group by hour label
  const groups: Record<string, Anomaly[]> = {};
  for (const a of anoms) {
    const key = hourOf(a.window.from);
    (groups[key] ??= []).push(a);
  }

  const counts = anoms.reduce<Record<string, number>>((acc, a) => {
    acc[a.severity] = (acc[a.severity] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-white">Anomalies</h1>
        <div className="flex gap-2 text-xs">
          {(["critical", "warning", "info"] as const).map((s) => (
            <span
              key={s}
              className={`rounded border px-2 py-0.5 ${SEV_STYLE[s].chip}`}
            >
              {counts[s] ?? 0} {s}
            </span>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          API unreachable: {error}
        </div>
      )}

      {anoms.length === 0 && !error && (
        <div className="rounded-lg border border-edge bg-panel px-4 py-6 text-sm text-slate-500">
          No anomalies detected in the current window.
        </div>
      )}

      <div className="space-y-6">
        {Object.entries(groups).map(([hour, items]) => (
          <div key={hour}>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              {hour}
            </div>
            <div className="space-y-2 border-l border-edge">
              {items.map((a, i) => (
                <AnomalyItem key={`${a.kind}-${a.window.from}-${i}`} a={a} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
