"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { DEFAULT_STORE, STORES } from "../lib/api";

type StoreCtx = { store: string; setStore: (id: string) => void };

const Ctx = createContext<StoreCtx>({ store: DEFAULT_STORE, setStore: () => {} });

/**
 * Global selected-store provider. One source of truth for every page's
 * "All stores / Store 1 / Store 2" view, persisted to the URL (?store=) so a
 * view is shareable and survives reload, with a localStorage fallback. Kept off
 * next/navigation's useSearchParams (which needs a Suspense boundary) — pages
 * poll on an interval anyway, so a plain history.replaceState is enough.
 */
export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [store, setStoreState] = useState<string>(DEFAULT_STORE);

  useEffect(() => {
    try {
      const fromUrl = new URL(window.location.href).searchParams.get("store");
      const saved = fromUrl || window.localStorage.getItem("si.store");
      if (saved && STORES.some((s) => s.id === saved)) setStoreState(saved);
    } catch {
      /* ignore */
    }
  }, []);

  const setStore = useCallback((id: string) => {
    setStoreState(id);
    try {
      window.localStorage.setItem("si.store", id);
      const url = new URL(window.location.href);
      url.searchParams.set("store", id);
      window.history.replaceState({}, "", url.toString());
    } catch {
      /* ignore */
    }
  }, []);

  return <Ctx.Provider value={{ store, setStore }}>{children}</Ctx.Provider>;
}

export function useStore(): StoreCtx {
  return useContext(Ctx);
}
