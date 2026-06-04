"use client";

import { useEffect, useState } from "react";
import { getStoreInvestigation, storeLabel, type StoreIncident } from "../../lib/api";
import { useStore } from "../../components/StoreContext";
import { Card, PageHeader, Badge, Skeleton, EmptyState, ErrorBanner, cx } from "../../components/ui";
import ClipPlayer from "../../components/ClipPlayer";

const POLL_MS = 5000;

const DOT: Record<string, string> = { critical: "bg-red-500", warning: "bg-amber-400", info: "bg-sky-400" };
type Tone = "danger" | "warning" | "info";
const TONE: Record<string, Tone> = { critical: "danger", warning: "warning", info: "info" };

const KIND_LABEL: Record<string, string> = {
  unbilled_cash_approach: "Unbilled cash approach",
  billing_without_pos: "Billing activity (no POS)",
  long_unattended_dwell: "Long unattended dwell",
};

function clock(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  } catch { return ts; }
}

function IncidentCard({ inc }: { inc: StoreIncident }) {
  const [open, setOpen] = useState(false);
  const metricEntries = Object.entries(inc.metrics ?? {}).filter(([, v]) => v !== null && v !== undefined);
  return (
    <Card className="transition-colors hover:border-border-strong">
      <button onClick={() => setOpen((o) => !o)} className="w-full px-4 py-3 text-left">
        <div className="flex items-center gap-3">
          <span className={cx("h-2 w-2 rounded-full", DOT[inc.severity])} />
          <Badge tone={TONE[inc.severity]}>{inc.severity}</Badge>
          <span className="text-sm font-medium text-slate-200">{inc.title ?? KIND_LABEL[inc.kind] ?? inc.kind}</span>
          <Badge tone="neutral">{inc.camera}</Badge>
          <span className="ml-auto flex items-center gap-2 text-xs tabular-nums text-slate-500">
            {inc.clip_ref.available && <span className="text-accent-hover">▶ footage</span>}
            {clock(inc.ts)}
            <span className={cx("transition-transform", open && "rotate-90")}>›</span>
          </span>
        </div>
        <div className="mt-2 pl-5 text-sm text-slate-300">{inc.summary ?? inc.evidence}</div>
        <div className="mt-1 pl-5 text-xs text-accent-hover">→ {inc.recommended_action}</div>
      </button>
      {open && (
        <div className="border-t border-border px-4 pb-4 pt-1">
          {/* clip_ref is a superset of Clip (extra from/to/review); ClipPlayer guards on .available */}
          <ClipPlayer clip={inc.clip_ref as unknown as import("../../lib/api").Clip} review={inc.clip_ref.review} />
          {metricEntries.length > 0 && (
            <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
              {metricEntries.map(([k, v]) => (
                <div key={k} className="rounded-lg border border-border bg-bg px-3 py-2">
                  <div className="text-[10px] uppercase tracking-wide text-slate-500">{k.replace(/_/g, " ")}</div>
                  <div className="mt-1 text-sm font-medium tabular-nums text-slate-200">{String(v)}</div>
                </div>
              ))}
            </div>
          )}
          {inc.supporting_events?.length > 0 && (
            <div className="mt-3 overflow-hidden rounded-lg border border-border">
              <div className="border-b border-border bg-bg px-3 py-2 text-[11px] uppercase tracking-wide text-slate-500">
                Supporting event log
              </div>
              <div className="divide-y divide-border">
                {inc.supporting_events.map((ev, idx) => (
                  <div key={`${ev.ts}-${idx}`} className="grid grid-cols-2 gap-2 px-3 py-2 text-xs sm:grid-cols-[88px_72px_1fr_80px]">
                    <span className="tabular-nums text-slate-500">{clock(ev.ts)}</span>
                    <span className="text-slate-400">{ev.camera ?? "—"}</span>
                    <span className="font-mono text-slate-300">{ev.event_type}</span>
                    <span className="truncate text-right text-slate-500">
                      {ev.queue_depth != null ? `q=${ev.queue_depth}` : ev.zone ?? "—"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
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
  const { store } = useStore();
  const [incidents, setIncidents] = useState<StoreIncident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const tick = async () => {
      try {
        const r = await getStoreInvestigation(store);
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
  }, [store]);

  const counts = incidents.reduce<Record<string, number>>((a, i) => {
    a[i.severity] = (a[i.severity] ?? 0) + 1; return a;
  }, {});

  return (
    <div className="space-y-6">
      <PageHeader title="Investigation"
        subtitle={`Loss-prevention review prompts — behavioural, identity-free. ${storeLabel(store)}.`}
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
        <EmptyState>
          No incidents flagged for this store/window
          {store === "STORE_BLR_009" && " — run the Store 2 detection pipeline to populate"}.
        </EmptyState>
      )}

      {!loading && (
        <div className="space-y-2">
          {incidents.map((inc, i) => <IncidentCard key={`${inc.kind}-${inc.ts}-${i}`} inc={inc} />)}
        </div>
      )}
    </div>
  );
}
