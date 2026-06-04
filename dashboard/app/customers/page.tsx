"use client";

import { useEffect, useState } from "react";
import { getStoreCustomers, storeLabel, type StoreCustomers } from "../../lib/api";
import { useStore } from "../../components/StoreContext";
import { Card, PageHeader, StatCard, NoDataStat, Skeleton, ErrorBanner } from "../../components/ui";

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
  const { store } = useStore();
  const [seg, setSeg] = useState<StoreCustomers | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const tick = async () => {
      try {
        const r = await getStoreCustomers(store);
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
  }, [store]);

  const rupees = (n: number) => "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  const cv = seg?.cv_customers ?? seg?.customers;
  const pos = seg?.pos_customers;
  const noPos = store === "STORE_BLR_009" || (!!seg?.note && seg.note.includes("No POS"));

  return (
    <div className="space-y-6">
      <PageHeader title="Customers"
        subtitle={`CV unique shoppers, shopping party, and POS repeat/basket context. ${storeLabel(store)}.`} />

      {error && <ErrorBanner message={error} />}

      {seg?.note && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-300">
          {seg.note}
        </div>
      )}

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard loading={loading} label="Unique shoppers" value={cv?.unique}
          sub={cv?.basis} emphasis />
        <StatCard loading={loading} label="Zone visitors" value={cv?.zone_visitors}
          sub="entered a merchandise zone" />
        <StatCard loading={loading} label="Billing visitors" value={cv?.billing_visitors}
          sub={noPos ? "seen on billing camera" : "matched against POS where possible"} />
        <StatCard loading={loading} label="Entry parties" value={seg?.shopping_party.entry_detected}
          sub="door-camera grouped" />
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SplitCard label={`Shopping party (entry-detected: ${seg?.shopping_party.entry_detected ?? 0})`} loading={loading}
          a={seg?.shopping_party.solo ?? 0} aLabel="Solo"
          b={seg?.shopping_party.group ?? 0} bLabel="Group" />
        {noPos ? (
          <NoDataStat label="New vs repeat" reason="POS customer IDs unavailable — no POS feed for Store 2" />
        ) : (
          <SplitCard label="New vs repeat (POS)" loading={loading}
            a={pos ? pos.unique - pos.repeat : 0} aLabel="New"
            b={pos?.repeat ?? 0} bLabel="Repeat" />
        )}
      </section>

      {noPos ? (
        <Card className="px-4 py-6 text-sm text-slate-400">
          Basket value, items/bill and repeat-purchase metrics are derived from the POS export, which
          Store 2 doesn&apos;t have. The shopping-party split above (solo vs group) is CV-only and
          works without POS.
        </Card>
      ) : (
        <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard loading={loading} label="POS customers" value={pos?.unique}
            sub={`repeat rate ${pos ? (pos.repeat_rate * 100).toFixed(0) : "—"}%`} />
          <StatCard loading={loading} label="Avg items / bill" value={seg?.basket.avg_items_per_bill} />
          <StatCard loading={loading} label="Avg basket value"
            value={seg ? rupees(seg.basket.avg_value_per_bill) : undefined} emphasis />
          <StatCard loading={loading} label="Multi-brand bills" value={seg?.basket.multi_brand_bills}
            sub={`of ${seg?.basket.bills ?? 0} bills · avg ${seg?.basket.avg_brands_per_bill ?? 0} brands`} />
        </section>
      )}

      {!loading && seg && (
        <p className="text-xs text-slate-600">
          Shopping-party counts come from {seg.shopping_party.basis}; small here because the CV
          footfall clip is short.
        </p>
      )}
    </div>
  );
}
