import { ReactNode } from "react";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const TONE: Record<Tone, string> = {
  neutral: "bg-elevated text-slate-300 border-border-strong",
  accent: "bg-accent-soft text-accent-hover border-accent/40",
  success: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  warning: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  danger: "bg-red-500/10 text-red-300 border-red-500/30",
  info: "bg-sky-500/10 text-sky-300 border-sky-500/30",
};

export function cx(...c: (string | false | undefined | null)[]) {
  return c.filter(Boolean).join(" ");
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cx("rounded-xl border border-border bg-surface shadow-card", className)}>
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
        TONE[tone]
      )}
    >
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} />;
}

export function StatCard({
  label,
  value,
  sub,
  loading,
  emphasis,
}: {
  label: string;
  value?: string | number;
  sub?: ReactNode;
  loading?: boolean;
  emphasis?: boolean;
}) {
  return (
    <Card className="p-5 transition-colors hover:border-border-strong">
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </div>
      {loading ? (
        <Skeleton className="mt-2.5 h-8 w-20" />
      ) : (
        <div
          className={cx(
            "mt-2 text-3xl font-semibold tabular-nums tracking-tight",
            emphasis ? "text-accent-hover" : "text-white"
          )}
        >
          {value ?? "—"}
        </div>
      )}
      {sub && !loading && <div className="mt-1.5 text-xs text-slate-500">{sub}</div>}
      {sub && loading && <Skeleton className="mt-2 h-3 w-28" />}
    </Card>
  );
}

export function Bar({ value, max, tone = "accent" }: { value: number; max: number; tone?: Tone }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const fill =
    tone === "accent" ? "bg-accent" : tone === "success" ? "bg-emerald-500" : "bg-slate-500";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-elevated">
      <div className={cx("h-full rounded-full transition-all duration-500", fill)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
      API unreachable — {message}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <Card className="px-4 py-10 text-center text-sm text-slate-500">{children}</Card>
  );
}

// A "value not available" stat (e.g. revenue for a store with no POS feed) —
// rendered muted with a reason so it never reads as a misleading ₹0.
export function NoDataStat({ label, reason }: { label: string; reason: string }) {
  return (
    <Card className="border-dashed p-5">
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 text-3xl font-semibold tracking-tight text-slate-600">—</div>
      <div className="mt-1.5 text-xs text-slate-600">{reason}</div>
    </Card>
  );
}

const AGE_ORDER = ["0-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"];

// Best-effort demographics: a gender split bar + an age-bucket histogram, shown
// as proportions so the panel reads coherently regardless of sample size. Used
// on both Live and Stores. Clearly labelled as a directional estimate.
export function DemographicsPanel({
  gender,
  age,
  note,
  loading,
}: {
  gender: Record<string, number>;
  age: Record<string, number>;
  note?: string;
  loading?: boolean;
}) {
  const f = (gender["F"] ?? 0) + (gender["Female"] ?? 0);
  const m = (gender["M"] ?? 0) + (gender["Male"] ?? 0);
  const gTotal = f + m;
  const fPct = gTotal ? Math.round((f / gTotal) * 100) : 0;
  const ageEntries = Object.entries(age).sort(
    (a, b) => AGE_ORDER.indexOf(a[0]) - AGE_ORDER.indexOf(b[0])
  );
  const aMax = Math.max(1, ...ageEntries.map(([, n]) => n));
  const aTotal = ageEntries.reduce((s, [, n]) => s + n, 0) || 1;
  const empty = gTotal === 0 && ageEntries.length === 0;

  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center gap-2 text-sm font-medium text-white">
        Demographics <Badge tone="neutral">best-effort</Badge>
      </div>
      <p className="mb-4 text-xs text-slate-500">
        {note ?? "Body/VLM estimate on face-blurred footage — directional only."}
      </p>
      {loading && <Skeleton className="h-24 w-full" />}
      {!loading && empty && (
        <p className="text-xs text-slate-500">No demographic signals in this window.</p>
      )}
      {!loading && !empty && (
        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <div className="mb-2 flex justify-between text-[11px] uppercase tracking-wider text-slate-500">
              <span>Gender</span>
              <span>{gTotal} visitors (est.)</span>
            </div>
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-elevated">
              <div className="h-full bg-accent transition-all duration-500" style={{ width: `${fPct}%` }} />
              <div className="h-full bg-sky-500/70 transition-all duration-500" style={{ width: `${100 - fPct}%` }} />
            </div>
            <div className="mt-2 flex justify-between text-xs text-slate-300">
              <span><span className="text-accent-hover">●</span> Female {fPct}% <span className="text-slate-500">({f})</span></span>
              <span>Male {100 - fPct}% <span className="text-slate-500">({m})</span> <span className="text-sky-400">●</span></span>
            </div>
          </div>
          <div>
            <div className="mb-2 text-[11px] uppercase tracking-wider text-slate-500">Age bucket</div>
            <div className="space-y-1.5">
              {ageEntries.length === 0 && <p className="text-xs text-slate-500">No age signal.</p>}
              {ageEntries.map(([b, n]) => (
                <div key={b} className="flex items-center gap-2">
                  <span className="w-12 shrink-0 text-[11px] tabular-nums text-slate-400">{b}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-elevated">
                    <div className="h-full rounded-full bg-accent/80 transition-all duration-500" style={{ width: `${(n / aMax) * 100}%` }} />
                  </div>
                  <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-slate-500">
                    {Math.round((n / aTotal) * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
