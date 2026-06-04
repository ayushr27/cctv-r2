"use client";

import { STORES } from "../lib/api";
import { useStore } from "./StoreContext";
import { cx } from "./ui";

const SHORT: Record<string, string> = {
  ALL: "All stores",
  STORE_BLR_002: "Store 1",
  STORE_BLR_009: "Store 2",
};

/** Global All / Store 1 / Store 2 switcher — lives in the sticky header so it
 *  drives every page through StoreContext. */
export default function StoreSwitcher() {
  const { store, setStore } = useStore();
  return (
    <div className="flex gap-0.5 rounded-lg border border-border bg-surface p-0.5">
      {STORES.map((s) => (
        <button
          key={s.id}
          onClick={() => setStore(s.id)}
          title={s.label}
          className={cx(
            "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
            store === s.id
              ? "bg-accent text-white shadow-pop"
              : "text-slate-400 hover:text-slate-200"
          )}
        >
          {SHORT[s.id] ?? s.label}
        </button>
      ))}
    </div>
  );
}
