"use client";

import { useEffect, useState } from "react";
import { getBrands, type BrandStand } from "../../lib/api";
import { Card, PageHeader, Badge, Skeleton, Bar, ErrorBanner } from "../../components/ui";

const POLL_MS = 5000;

function rupees(n: number): string {
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function signalTone(signal: string): "warning" | "success" | "neutral" {
  if (signal.includes("low conversion") || signal.includes("opportunity")) return "warning";
  if (signal.includes("converting")) return "success";
  return "neutral";
}

export default function BrandsPage() {
  const [stands, setStands] = useState<BrandStand[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getBrands();
        if (!alive) return;
        setStands(r.stands); setError(null);
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

  const maxAttn = Math.max(1, ...stands.map((s) => s.attention_seconds));

  return (
    <div className="space-y-6">
      <PageHeader title="Brand stands"
        subtitle="Customer attention (dwell) joined to POS outcome — revenue, units and top products. Aggregate & identity-free." />

      {error && <ErrorBanner message={error} />}

      <div className="space-y-3">
        {loading &&
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="p-5"><Skeleton className="h-24 w-full" /></Card>
          ))}

        {!loading && stands.map((s) => (
          <Card key={s.stand} className="p-5 transition-colors hover:border-border-strong">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">{s.stand}</span>
              {s.camera && <Badge tone="neutral">{s.camera}</Badge>}
              <span className="ml-auto"><Badge tone={signalTone(s.signal)}>{s.signal}</Badge></span>
            </div>

            <div className="mt-4">
              <div className="mb-1.5 flex justify-between text-[11px] text-slate-500">
                <span>Attention</span>
                <span className="tabular-nums">{s.attention_seconds}s · {(s.attention_share * 100).toFixed(0)}%</span>
              </div>
              <Bar value={s.attention_seconds} max={maxAttn} />
            </div>

            <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
              <Metric label="Visits" value={String(s.visits)} />
              <Metric label="Revenue" value={rupees(s.revenue)} tone="text-emerald-300" />
              <Metric label="Units" value={String(s.units)} />
              <Metric label="₹ / visit" value={rupees(s.revenue_per_visit)} />
            </div>

            {s.top_products.length > 0 && (
              <div className="mt-3 border-t border-border pt-3 text-xs text-slate-500">
                <span className="text-slate-400">Top products:</span>{" "}
                {s.top_products.map((p) => `${p.product} (${p.units})`).join("  ·  ")}
              </div>
            )}
            <div className="mt-2 text-[11px] text-slate-600">{s.brands.join(" · ")}</div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-0.5 text-sm font-medium tabular-nums ${tone ?? "text-slate-200"}`}>{value}</div>
    </div>
  );
}
