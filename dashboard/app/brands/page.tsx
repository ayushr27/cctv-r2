"use client";

import { useEffect, useState } from "react";
import { getBrands, type BrandStand } from "../../lib/api";

const POLL_MS = 5000;

function rupees(n: number): string {
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function signalChip(signal: string): string {
  if (signal.includes("low conversion") || signal.includes("opportunity"))
    return "bg-amber-950 text-amber-300 border-amber-800";
  if (signal.includes("converting")) return "bg-emerald-950 text-emerald-300 border-emerald-800";
  return "bg-edge text-slate-400 border-edge";
}

export default function BrandsPage() {
  const [stands, setStands] = useState<BrandStand[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getBrands();
        if (!alive) return;
        setStands(r.stands);
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

  const maxAttn = Math.max(1, ...stands.map((s) => s.attention_seconds));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-white">Brand stands</h1>
      <p className="rounded-lg border border-edge bg-panel px-4 py-3 text-xs text-slate-400">
        Customer <span className="text-slate-200">attention</span> at each brand stand
        (dwell, staff excluded) joined to POS <span className="text-slate-200">outcome</span>
        {" "}(revenue, units, top products sold). Aggregate &amp; identity-free — “top
        products” is what <em>sells</em> from the brand, not what any individual likes.
      </p>

      {error && (
        <div className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          API unreachable: {error}
        </div>
      )}

      {stands.length === 0 && !error && (
        <div className="rounded-lg border border-edge bg-panel px-4 py-6 text-sm text-slate-500">
          No brand-stand activity in the current window.
        </div>
      )}

      <div className="space-y-3">
        {stands.map((s) => (
          <div key={s.stand} className="rounded-xl border border-edge bg-panel p-4">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-white">{s.stand}</span>
              {s.camera && (
                <span className="rounded bg-edge px-1.5 py-0.5 text-[10px] uppercase text-slate-400">
                  {s.camera}
                </span>
              )}
              <span className={`ml-auto rounded border px-2 py-0.5 text-[10px] ${signalChip(s.signal)}`}>
                {s.signal}
              </span>
            </div>

            {/* attention bar */}
            <div className="mt-3 h-2 w-full overflow-hidden rounded bg-ink">
              <div
                className="h-full bg-sky-500/70"
                style={{ width: `${(s.attention_seconds / maxAttn) * 100}%` }}
              />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-slate-400 md:grid-cols-4">
              <span>Attention: <span className="text-slate-200">{s.attention_seconds}s</span> ({(s.attention_share * 100).toFixed(0)}%)</span>
              <span>Visits: <span className="text-slate-200">{s.visits}</span></span>
              <span>Revenue: <span className="text-emerald-300">{rupees(s.revenue)}</span></span>
              <span>Units: <span className="text-slate-200">{s.units}</span></span>
              <span>₹/visit: <span className="text-slate-200">{rupees(s.revenue_per_visit)}</span></span>
              <span>₹/attn-min: <span className="text-slate-200">{rupees(s.revenue_per_attention_min)}</span></span>
            </div>

            {s.top_products.length > 0 && (
              <div className="mt-2 text-xs text-slate-500">
                Top products sold:{" "}
                {s.top_products.map((p) => `${p.product} (${p.units})`).join(", ")}
              </div>
            )}
            <div className="mt-1 text-[11px] text-slate-600">{s.brands.join(" · ")}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
