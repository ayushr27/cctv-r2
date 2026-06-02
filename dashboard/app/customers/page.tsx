"use client";

import { useEffect, useState } from "react";
import { getCustomers, type CustomerSegments } from "../../lib/api";

const POLL_MS = 5000;

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-edge bg-panel p-5">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-2 text-3xl font-semibold text-white tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function Split({ label, a, aLabel, b, bLabel }: {
  label: string; a: number; aLabel: string; b: number; bLabel: string;
}) {
  const total = a + b || 1;
  const pa = (a / total) * 100;
  return (
    <div className="rounded-xl border border-edge bg-panel p-5">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-3 flex h-3 w-full overflow-hidden rounded bg-ink">
        <div className="h-full bg-sky-500/70" style={{ width: `${pa}%` }} />
        <div className="h-full bg-fuchsia-500/60" style={{ width: `${100 - pa}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-xs text-slate-400">
        <span><span className="text-sky-300">●</span> {aLabel}: <span className="text-slate-200">{a}</span></span>
        <span><span className="text-fuchsia-300">●</span> {bLabel}: <span className="text-slate-200">{b}</span></span>
      </div>
    </div>
  );
}

export default function CustomersPage() {
  const [seg, setSeg] = useState<CustomerSegments | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getCustomers();
        if (!alive) return;
        setSeg(r);
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

  const rupees = (n: number) => "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-white">Customers</h1>
      <p className="rounded-lg border border-edge bg-panel px-4 py-3 text-xs text-slate-400">
        Non-demographic segments — <span className="text-slate-200">no gender/age is inferred
        or stored</span> (the POS has no such field and CV inference would be biased &amp;
        unreliable). These use real signals: shopping party (CV), repeat purchase &amp; basket (POS).
      </p>

      {error && (
        <div className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          API unreachable: {error}
        </div>
      )}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Split
          label="Shopping party (CV footfall)"
          a={seg?.shopping_party.solo ?? 0} aLabel="Solo"
          b={seg?.shopping_party.group ?? 0} bLabel="Group"
        />
        <Split
          label="New vs repeat (POS)"
          a={(seg ? seg.customers.unique - seg.customers.repeat : 0)} aLabel="New"
          b={seg?.customers.repeat ?? 0} bLabel="Repeat"
        />
      </section>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Unique customers" value={seg ? String(seg.customers.unique) : "—"}
          sub={`repeat rate ${seg ? (seg.customers.repeat_rate * 100).toFixed(0) : "—"}%`} />
        <Stat label="Avg items / bill" value={seg ? String(seg.basket.avg_items_per_bill) : "—"} />
        <Stat label="Avg basket value" value={seg ? rupees(seg.basket.avg_value_per_bill) : "—"} />
        <Stat label="Multi-brand bills" value={seg ? String(seg.basket.multi_brand_bills) : "—"}
          sub={`of ${seg?.basket.bills ?? 0} bills · avg ${seg?.basket.avg_brands_per_bill ?? 0} brands`} />
      </section>

      {seg?.shopping_party && (
        <p className="text-xs text-slate-600">
          Shopping-party counts come from {seg.shopping_party.basis}; they are small here
          because the CV footfall clip is short.
        </p>
      )}
    </div>
  );
}
