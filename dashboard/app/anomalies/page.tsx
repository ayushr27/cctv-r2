"use client";

import { useEffect, useState } from "react";
import { getAnomalies, type Anomaly } from "../../lib/api";
import { PageHeader, Badge, Skeleton, EmptyState, ErrorBanner, cx } from "../../components/ui";
import ClipPlayer from "../../components/ClipPlayer";

const POLL_MS = 5000;

const DOT: Record<string, string> = {
  critical: "bg-red-500", warning: "bg-amber-400", info: "bg-sky-400",
};
type Tone = "danger" | "warning" | "info";
const TONE: Record<string, Tone> = { critical: "danger", warning: "warning", info: "info" };

function hourOf(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
  } catch { return ts; }
}

function Item({ a }: { a: Anomaly }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative pl-6">
      <span className={cx("absolute left-1.5 top-3.5 h-2.5 w-2.5 rounded-full ring-4 ring-bg", DOT[a.severity])} />
      <div className="rounded-lg border border-border bg-surface transition-colors hover:border-border-strong">
        <button onClick={() => setOpen((o) => !o)} className="w-full px-4 py-3 text-left">
          <div className="flex items-center gap-3">
            <Badge tone={TONE[a.severity]}>{a.severity}</Badge>
            <span className="font-mono text-xs text-slate-400">{a.kind}</span>
            {a.camera && <Badge tone="neutral">{a.camera}</Badge>}
            <span className="ml-auto flex items-center gap-2 text-xs tabular-nums text-slate-500">
              {a.clip?.available && <span className="text-accent-hover">▶ footage</span>}
              {hourOf(a.window.from)}
              <span className={cx("transition-transform", open && "rotate-90")}>›</span>
            </span>
          </div>
          <div className="mt-1.5 text-sm text-slate-300">{a.evidence}</div>
        </button>
        {open && (
          <div className="border-t border-border px-4 pb-4 pt-1">
            <ClipPlayer clip={a.clip} review={`Review ${a.camera ?? ""} around ${hourOf(a.window.from)}`} />
            <details className="mt-3">
              <summary className="cursor-pointer text-[11px] uppercase tracking-wide text-slate-500 hover:text-slate-300">
                Raw anomaly JSON
              </summary>
              <pre className="mt-2 overflow-x-auto rounded-lg border border-border bg-bg p-3 text-[11px] text-slate-400">
{JSON.stringify(a, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

export default function AnomaliesPage() {
  const [anoms, setAnoms] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getAnomalies();
        if (!alive) return;
        setAnoms(r.anomalies); setError(null);
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

  const counts = anoms.reduce<Record<string, number>>((a, x) => {
    a[x.severity] = (a[x.severity] ?? 0) + 1; return a;
  }, {});

  const groups: Record<string, Anomaly[]> = {};
  for (const a of anoms) (groups[hourOf(a.window.from)] ??= []).push(a);

  return (
    <div className="space-y-6">
      <PageHeader title="Anomalies" subtitle="Statistical detectors over the event stream, with evidence."
        actions={
          <div className="flex gap-2">
            {(["critical", "warning", "info"] as const).map((s) => (
              <Badge key={s} tone={TONE[s]}>{counts[s] ?? 0} {s}</Badge>
            ))}
          </div>
        } />

      {error && <ErrorBanner message={error} />}

      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)}
        </div>
      )}

      {!loading && anoms.length === 0 && !error && (
        <EmptyState>No anomalies detected in the current window.</EmptyState>
      )}

      {!loading && (
        <div className="space-y-6">
          {Object.entries(groups).map(([hour, items]) => (
            <div key={hour}>
              <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-500">{hour}</div>
              <div className="space-y-2 border-l border-border">
                {items.map((a, i) => <Item key={`${a.kind}-${a.window.from}-${i}`} a={a} />)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
