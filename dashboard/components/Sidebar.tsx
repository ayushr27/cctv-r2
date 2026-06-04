"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "./ui";

// Minimal inline icons (lucide-style) — no icon dependency.
const I = {
  live: "M3 12h4l3 8 4-16 3 8h4",
  stores: "M3 9h18M3 9l1.5-5h15L21 9M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M9 20v-6h6v6",
  funnel: "M3 4h18l-7 8v6l-4 2v-8z",
  brands: "M20.59 13.41 11 3.99 4 4l-.01 7 9.42 9.42a2 2 0 0 0 2.83 0l4.35-4.18a2 2 0 0 0 0-2.83zM7.5 8.5h.01",
  customers: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm13 10v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  anomalies: "M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4m0 4h.01",
  investigation: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
};

const NAV: { href: string; label: string; icon: keyof typeof I }[] = [
  { href: "/", label: "Live", icon: "live" },
  { href: "/stores", label: "Stores", icon: "stores" },
  { href: "/funnel", label: "Funnel", icon: "funnel" },
  { href: "/brands", label: "Brands", icon: "brands" },
  { href: "/customers", label: "Customers", icon: "customers" },
  { href: "/anomalies", label: "Anomalies", icon: "anomalies" },
  { href: "/investigation", label: "Investigation", icon: "investigation" },
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px] shrink-0">
      <path d={d} />
    </svg>
  );
}

export default function Sidebar() {
  const path = usePathname();
  return (
    <aside className="fixed inset-y-0 left-0 z-20 flex w-60 flex-col border-r border-border bg-surface">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-white shadow-pop">
          <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" stroke="currentColor" strokeWidth="2">
            <path d="M3 9h18M3 9l1.5-5h15L21 9M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9" strokeLinejoin="round" />
          </svg>
        </span>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">Store Intelligence</div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Brigade · Bangalore</div>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 px-3 py-2">
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              className={cx(
                "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent-soft text-white"
                  : "text-slate-400 hover:bg-elevated hover:text-slate-200"
              )}
            >
              <span className={active ? "text-accent-hover" : "text-slate-500 group-hover:text-slate-300"}>
                <Icon d={I[n.icon]} />
              </span>
              {n.label}
              {active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-accent" />}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border px-5 py-3 text-[10px] leading-relaxed text-slate-600">
        Privacy-preserving · no faces / no PII
      </div>
    </aside>
  );
}
