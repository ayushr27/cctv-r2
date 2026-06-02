"use client";

import { useEffect, useState } from "react";
import { getCustomers, type CustomerSegments } from "../../lib/api";
import { Card, PageHeader, StatCard, Skeleton, ErrorBanner } from "../../components/ui";

const POLL_MS = 5000;

function SplitCard({ label, a, aLabel, b, bLabel, loading }: {
  label: string; a: number; aLabel: string; b: number; bLabel: string; loading: boolean;
}) {
  const total = a + b || 1;
  const pa = (a / total) * 100;
  return (
    <Card className="p-5">
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">{label}</div>
      {loading ? (
        <Skeleton className="mt-4 h-3 w-full" />
      ) : (
        <>
          <div className="mt-4 flex h-2.5 w-full overflow-hidden rounded-full bg-elevated">
            <div className="h-full bg-accent transition-all duration-500" style={{ width: `${pa}%` }} />
            <div className="h-full bg-slate-600 transition-all duration-500" style={{ width: `${100 - pa}%` }} />
          </div>
          <div className="mt-2.5 flex justify-between text-xs text-slate-400">
            <span><span className="text-accent-hover">●</span> {aLabel}: <span className="font-medium text-slate-200">{a}</span></span>
            <span><span className="text-slate-500">●</span> {bLabel}: <span className="font-medium text-slate-200">{b}</span></span>
          </div>
        </>
      )}
    </Card>
  );
}

export default function CustomersPage() {
  const [seg, setSeg] = useState<CustomerSegments | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getCustomers();
        if (!alive) return;
        setSeg(r); setError(null);
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

  const rupees = (n: number) => "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });

  return (
    <div className="space-y-6">
      <PageHeader title="Customers"
        subtitle="Non-demographic segments — no gender/age inferred or stored. Shopping party (CV), repeat purchase & basket (POS)." />

      {error && <ErrorBanner message={error} />}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SplitCard label="Shopping party (CV footfall)" loading={loading}
          a={seg?.shopping_party.solo ?? 0} aLabel="Solo"
          b={seg?.shopping_party.group ?? 0} bLabel="Group" />
        <SplitCard label="New vs repeat (POS)" loading={loading}
          a={seg ? seg.customers.unique - seg.customers.repeat : 0} aLabel="New"
          b={seg?.customers.repeat ?? 0} bLabel="Repeat" />
      </section>

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard loading={loading} label="Unique customers" value={seg?.customers.unique}
          sub={`repeat rate ${seg ? (seg.customers.repeat_rate * 100).toFixed(0) : "—"}%`} />
        <StatCard loading={loading} label="Avg items / bill" value={seg?.basket.avg_items_per_bill} />
        <StatCard loading={loading} label="Avg basket value"
          value={seg ? rupees(seg.basket.avg_value_per_bill) : undefined} emphasis />
        <StatCard loading={loading} label="Multi-brand bills" value={seg?.basket.multi_brand_bills}
          sub={`of ${seg?.basket.bills ?? 0} bills · avg ${seg?.basket.avg_brands_per_bill ?? 0} brands`} />
      </section>

      {!loading && seg && (
        <p className="text-xs text-slate-600">
          Shopping-party counts come from {seg.shopping_party.basis}; small here because the CV
          footfall clip is short.
        </p>
      )}
    </div>
  );
}
