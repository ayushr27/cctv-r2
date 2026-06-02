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
