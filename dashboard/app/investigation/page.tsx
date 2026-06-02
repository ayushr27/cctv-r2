"use client";

import { useEffect, useState } from "react";
import { getInvestigation, type Incident } from "../../lib/api";

const POLL_MS = 5000;

const SEV: Record<string, { dot: string; chip: string; label: string }> = {
  critical: { dot: "bg-red-500", chip: "bg-red-950 text-red-300 border-red-800", label: "Critical" },
  warning: { dot: "bg-amber-400", chip: "bg-amber-950 text-amber-300 border-amber-800", label: "Warning" },
  info: { dot: "bg-sky-400", chip: "bg-sky-950 text-sky-300 border-sky-800", label: "Info" },
};

const KIND_LABEL: Record<string, string> = {
  unbilled_cash_approach: "Unbilled cash approach",
  long_unattended_dwell: "Long unattended dwell",
};

function clock(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-IN", {
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  } catch {
    return ts;
  }
}

function IncidentCard({ inc }: { inc: Incident }) {
  const [open, setOpen] = useState(false);
  const sev = SEV[inc.severity] ?? SEV.info;
  return (
    <div className="rounded-lg border border-edge bg-panel">
      <button onClick={() => setOpen((o) => !o)} className="w-full px-4 py-3 text-left">
        <div className="flex items-center gap-3">
          <span className={`h-2.5 w-2.5 rounded-full ${sev.dot}`} />
          <span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase ${sev.chip}`}>
            {sev.label}
          </span>
          <span className="text-sm font-medium text-slate-200">
            {KIND_LABEL[inc.kind] ?? inc.kind}
          </span>
          <span className="rounded bg-edge px-1.5 py-0.5 text-[10px] uppercase text-slate-300">
            {inc.camera}
          </span>
          <span className="ml-auto text-xs tabular-nums text-slate-400">{clock(inc.ts)}</span>
        </div>
        <div className="mt-1.5 pl-6 text-sm text-slate-300">{inc.evidence}</div>
        <div className="mt-2 pl-6 text-xs text-emerald-300">🎞 {inc.clip_ref.review}</div>
        {open && (
          <pre className="mt-3 overflow-x-auto rounded bg-ink p-3 text-[11px] text-slate-400">
{JSON.stringify(inc, null, 2)}
          </pre>
        )}
      </button>
    </div>
  );
}

export default function InvestigationPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [note, setNote] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getInvestigation();
        if (!alive) return;
        setIncidents(r.incidents);
        setNote(r.note ?? "");
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

  const counts = incidents.reduce<Record<string, number>>((a, i) => {
    a[i.severity] = (a[i.severity] ?? 0) + 1;
    return a;
  }, {});

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-white">Investigation</h1>
        <div className="flex gap-2 text-xs">
          {(["critical", "warning", "info"] as const).map((s) => (
            <span key={s} className={`rounded border px-2 py-0.5 ${SEV[s].chip}`}>
              {counts[s] ?? 0} {s}
            </span>
          ))}
        </div>
      </div>

      <p className="rounded-lg border border-edge bg-panel px-4 py-3 text-xs text-slate-400">
        🔒 Privacy-preserving: these are <span className="text-slate-200">behavioural review prompts</span>,
        not accusations — no faces or identity are stored. Each card gives a camera +
        timestamp so a reviewer can pull the secured footage
        (<code className="text-slate-300">make clip CAM=… AT=…</code>).
      </p>

      {error && (
        <div className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          API unreachable: {error}
        </div>
      )}

      {incidents.length === 0 && !error && (
        <div className="rounded-lg border border-edge bg-panel px-4 py-6 text-sm text-slate-500">
          No incidents flagged in the current window.
        </div>
      )}

      <div className="space-y-2">
        {incidents.map((inc, i) => (
          <IncidentCard key={`${inc.kind}-${inc.ts}-${i}`} inc={inc} />
        ))}
      </div>
    </div>
  );
}
