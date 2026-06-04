"use client";

import { useEffect, useState } from "react";
import {
  getStoreAnomalies,
  getStoreInvestigation,
  storeLabel,
  type StoreAnomaly,
  type StoreIncident,
} from "../../lib/api";
import { useStore } from "../../components/StoreContext";
import { Card, PageHeader, Badge, Skeleton, EmptyState, ErrorBanner, cx } from "../../components/ui";

const POLL_MS = 5000;

type Tone = "danger" | "warning" | "info";
const TONE: Record<string, Tone> = { CRITICAL: "danger", WARN: "warning", INFO: "info" };
const DOT: Record<string, string> = { CRITICAL: "bg-red-500", WARN: "bg-amber-400", INFO: "bg-sky-400" };
const INCIDENT_TONE: Record<string, Tone> = { critical: "danger", warning: "warning", info: "info" };
const INCIDENT_DOT: Record<string, string> = { critical: "bg-red-500", warning: "bg-amber-400", info: "bg-sky-400" };

export default function AnomaliesPage() {
  const { store } = useStore();
  const [anoms, setAnoms] = useState<StoreAnomaly[]>([]);
  const [incidents, setIncidents] = useState<StoreIncident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const tick = async () => {
      try {
        const [r, inv] = await Promise.all([
          getStoreAnomalies(store),
          getStoreInvestigation(store),
        ]);
        if (!alive) return;
        setAnoms(r.anomalies);
        setIncidents(inv.incidents);
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

  const anomalyIncidentKeys = new Set(
    anoms
      .filter((a) => a.type === "INCIDENT_REVIEW")
      .map((a) => `${a.incident_kind ?? ""}-${a.ts ?? ""}`)
  );
  const incidentCards = incidents.filter((inc) => !anomalyIncidentKeys.has(`${inc.kind}-${inc.ts}`));

  const counts = anoms.reduce<Record<string, number>>((a, x) => {
    a[x.severity] = (a[x.severity] ?? 0) + 1; return a;
  }, {});
  for (const inc of incidentCards) {
    const sev = inc.severity === "critical" ? "CRITICAL" : inc.severity === "warning" ? "WARN" : "INFO";
    counts[sev] = (counts[sev] ?? 0) + 1;
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Anomalies"
        subtitle={`Operational detectors over the event stream — ${storeLabel(store)}.`}
        actions={
          <div className="flex gap-2">
            {(["CRITICAL", "WARN", "INFO"] as const).map((s) => (
              <Badge key={s} tone={TONE[s]}>{counts[s] ?? 0} {s.toLowerCase()}</Badge>
            ))}
          </div>
        } />

      {error && <ErrorBanner message={error} />}

      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      )}

      {!loading && anoms.length === 0 && incidentCards.length === 0 && !error && (
        <EmptyState>
          No anomalies detected for this store/window
          {store === "STORE_BLR_009" && " — run the Store 2 detection pipeline to populate"}.
        </EmptyState>
      )}

      {!loading && (
        <div className="space-y-2">
          {anoms.map((a, i) => (
            <Card key={`${a.type}-${i}`} className="p-4 transition-colors hover:border-border-strong">
              <div className="flex items-center gap-3">
                <span className={cx("h-2 w-2 rounded-full", DOT[a.severity])} />
                <Badge tone={TONE[a.severity]}>{a.severity}</Badge>
                <span className="font-mono text-xs text-slate-400">{a.type}</span>
                {a.zone_id && <Badge tone="neutral">{a.zone_id}</Badge>}
                {a.observed !== undefined && (
                  <span className="ml-auto text-xs tabular-nums text-slate-500">observed {a.observed}</span>
                )}
              </div>
              <div className="mt-2 text-sm text-slate-300">{a.evidence}</div>
              <div className="mt-1.5 text-xs text-accent-hover">→ {a.suggested_action}</div>
            </Card>
          ))}
          {incidentCards.map((inc, i) => (
            <Card key={`${inc.kind}-${inc.ts}-${i}`} className="p-4 transition-colors hover:border-border-strong">
              <div className="flex items-center gap-3">
                <span className={cx("h-2 w-2 rounded-full", INCIDENT_DOT[inc.severity])} />
                <Badge tone={INCIDENT_TONE[inc.severity]}>{inc.severity}</Badge>
                <span className="font-mono text-xs text-slate-400">INCIDENT_REVIEW</span>
                <Badge tone="neutral">{inc.camera}</Badge>
                <span className="ml-auto text-xs tabular-nums text-slate-500">
                  {new Date(inc.ts).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}
                </span>
              </div>
              <div className="mt-2 text-sm font-medium text-slate-200">{inc.title}</div>
              <div className="mt-1 text-sm text-slate-300">{inc.summary}</div>
              <div className="mt-1.5 text-xs text-accent-hover">→ {inc.recommended_action}</div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
