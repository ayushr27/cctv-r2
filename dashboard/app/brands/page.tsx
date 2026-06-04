"use client";

import { useEffect, useState } from "react";
import { getStoreBrands, storeLabel, type StoreBrands } from "../../lib/api";
import { useStore } from "../../components/StoreContext";
import { Card, PageHeader, Badge, Skeleton, Bar, ErrorBanner } from "../../components/ui";

const POLL_MS = 5000;

const rupees = (n: number) => "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });

function signalTone(signal: string): "warning" | "success" | "neutral" {
  if (signal.includes("low conversion") || signal.includes("opportunity")) return "warning";
  if (signal.includes("converting")) return "success";
  return "neutral";
}

export default function BrandsPage() {
  const { store } = useStore();
  const [data, setData] = useState<StoreBrands | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const tick = async () => {
      try {
        const r = await getStoreBrands(store);
        if (!alive) return;
        setData(r); setError(null);
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

  const stands = data?.stands ?? [];
  const maxAttn = Math.max(1, ...stands.map((s) => s.attention_seconds));
  const noPos = store === "STORE_BLR_009" || (!!data?.note && data.note.includes("No POS"));

  return (
    <div className="space-y-6">
      <PageHeader title="Brand stands"
        subtitle={`Customer attention (dwell) joined to POS outcome — ${storeLabel(store)}. Aggregate & identity-free.`} />

      {error && <ErrorBanner message={error} />}

      {data?.note && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-300">
          {data.note}
        </div>
      )}

      <div className="space-y-3">
        {loading &&
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="p-5"><Skeleton className="h-24 w-full" /></Card>
          ))}

        {!loading && stands.length === 0 && (
          <Card className="px-4 py-10 text-center text-sm text-slate-500">
            No brand-stand activity in this window
            {store === "STORE_BLR_009" && " — run the Store 2 detection pipeline to populate"}.
          </Card>
        )}

        {!loading && stands.map((s) => (
          <Card key={s.stand} className="p-5 transition-colors hover:border-border-strong">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">{s.label}</span>
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
              {noPos ? (
                <Metric label="Attention share" value={`${(s.attention_share * 100).toFixed(0)}%`} />
              ) : (
                <>
                  <Metric label="Revenue" value={rupees(s.revenue)} tone="text-emerald-300" />
                  <Metric label="Units" value={String(s.units)} />
                  <Metric label="₹ / visit" value={rupees(s.revenue_per_visit)} />
                </>
              )}
            </div>

            {s.top_products.length > 0 && (
              <div className="mt-3 border-t border-border pt-3 text-xs text-slate-500">
                <span className="text-slate-400">Top products:</span>{" "}
                {s.top_products.map((p) => `${p.product} (${p.units})`).join("  ·  ")}
              </div>
            )}
            {s.brands.length > 0 && <div className="mt-2 text-[11px] text-slate-600">{s.brands.join(" · ")}</div>}
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
