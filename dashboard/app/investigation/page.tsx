"use client";

import { useEffect, useState } from "react";
import { getInvestigation, type Incident } from "../../lib/api";
import { Card, PageHeader, Badge, Skeleton, EmptyState, ErrorBanner, cx } from "../../components/ui";
import ClipPlayer from "../../components/ClipPlayer";

const POLL_MS = 5000;

const DOT: Record<string, string> = { critical: "bg-red-500", warning: "bg-amber-400", info: "bg-sky-400" };
type Tone = "danger" | "warning" | "info";
const TONE: Record<string, Tone> = { critical: "danger", warning: "warning", info: "info" };

const KIND_LABEL: Record<string, string> = {
  unbilled_cash_approach: "Unbilled cash approach",
  long_unattended_dwell: "Long unattended dwell",
};

function clock(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  } catch { return ts; }
}

function IncidentCard({ inc }: { inc: Incident }) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="transition-colors hover:border-border-strong">
      <button onClick={() => setOpen((o) => !o)} className="w-full px-4 py-3 text-left">
        <div className="flex items-center gap-3">
          <span className={cx("h-2 w-2 rounded-full", DOT[inc.severity])} />
          <Badge tone={TONE[inc.severity]}>{inc.severity}</Badge>
          <span className="text-sm font-medium text-slate-200">{KIND_LABEL[inc.kind] ?? inc.kind}</span>
          <Badge tone="neutral">{inc.camera}</Badge>
          <span className="ml-auto flex items-center gap-2 text-xs tabular-nums text-slate-500">
            {inc.clip_ref.available && <span className="text-accent-hover">▶ footage</span>}
            {clock(inc.ts)}
            <span className={cx("transition-transform", open && "rotate-90")}>›</span>
          </span>
        </div>
        <div className="mt-2 pl-5 text-sm text-slate-300">{inc.evidence}</div>
      </button>
      {open && (
        <div className="border-t border-border px-4 pb-4 pt-1">
          <ClipPlayer clip={inc.clip_ref as any} review={inc.clip_ref.review} />
          <details className="mt-3">
            <summary className="cursor-pointer text-[11px] uppercase tracking-wide text-slate-500 hover:text-slate-300">
              Raw incident JSON
            </summary>
            <pre className="mt-2 overflow-x-auto rounded-lg border border-border bg-bg p-3 text-[11px] text-slate-400">
{JSON.stringify(inc, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </Card>
  );
}

export default function InvestigationPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getInvestigation();
        if (!alive) return;
        setIncidents(r.incidents); setError(null);
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

  const counts = incidents.reduce<Record<string, number>>((a, i) => {
    a[i.severity] = (a[i.severity] ?? 0) + 1; return a;
  }, {});

  return (
    <div className="space-y-6">
      <PageHeader title="Investigation" subtitle="Loss-prevention review prompts — behavioural, identity-free."
        actions={
          <div className="flex gap-2">
            {(["critical", "warning", "info"] as const).map((s) => (
              <Badge key={s} tone={TONE[s]}>{counts[s] ?? 0} {s}</Badge>
            ))}
          </div>
        } />

      <Card className="border-accent/30 bg-accent-soft px-4 py-3 text-xs text-slate-300">
        Privacy-preserving: these are <span className="font-medium text-white">review prompts, not accusations</span> —
        no faces or identity stored. Each gives a camera + timestamp to pull the secured footage
        (<code className="text-accent-hover">make clip CAM=… AT=…</code>).
      </Card>

      {error && <ErrorBanner message={error} />}

      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      )}

      {!loading && incidents.length === 0 && !error && (
        <EmptyState>No incidents flagged in the current window.</EmptyState>
      )}

      {!loading && (
        <div className="space-y-2">
          {incidents.map((inc, i) => <IncidentCard key={`${inc.kind}-${inc.ts}-${i}`} inc={inc} />)}
        </div>
      )}
    </div>
  );
}
