// Typed client for the Store Intelligence API.
// Reads NEXT_PUBLIC_API_URL (default http://localhost:8000). Every call is
// cache: 'no-store' so the polling pages always see fresh data.

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

// ---- response types ----

export interface Metrics {
  window: { from: string | null; to: string | null };
  footfall: number;
  unique_groups: number;
  staff_count: number;
  peak_hour: string | null;
  avg_dwell_seconds: number;
  conversion_rate: number | null;
  avg_bill_value: number | null;
  total_revenue: number | null;
}

export interface FunnelStage {
  name: string;
  count: number;
}

export interface Funnel {
  stages: FunnelStage[];
  drop_off_rates: number[];
  raw_counts: Record<string, number>;
  window: { from: string | null; to: string | null };
  granularity?: string;
  by_hour?: { hour: string; stages: FunnelStage[] }[];
}

export interface Zone {
  name: string;
  camera: string | null;
  visits: number;
  total_dwell_seconds: number;
  avg_dwell_seconds: number;
  conversion_proxy: number;
  brands: string[];
  brand_revenue: number;
}

export interface ZonesResponse {
  window: { from: string | null; to: string | null };
  zones: Zone[];
  note?: string;
}

export interface Anomaly {
  kind: string;
  severity: "info" | "warning" | "critical";
  window: { from: string; to: string };
  observed: number;
  expected_p50: number | null;
  z_score: number | null;
  evidence: string;
}

export interface AnomaliesResponse {
  window: { from: string | null; to: string | null };
  kinds_available: string[];
  count: number;
  anomalies: Anomaly[];
}

export interface CustomerSegments {
  window: { from: string | null; to: string | null };
  shopping_party: { solo: number; group: number; group_rate: number; basis: string };
  customers: { unique: number; repeat: number; repeat_rate: number; basis: string };
  basket: {
    bills: number;
    avg_items_per_bill: number;
    avg_value_per_bill: number;
    single_brand_bills: number;
    multi_brand_bills: number;
    avg_brands_per_bill: number;
  };
  note?: string;
}

export interface BrandStand {
  stand: string;
  camera: string | null;
  brands: string[];
  visits: number;
  attention_seconds: number;
  attention_share: number;
  revenue: number;
  units: number;
  revenue_per_visit: number;
  revenue_per_attention_min: number;
  top_products: { product: string; units: number }[];
  signal: string;
}

export interface BrandsResponse {
  window: { from: string | null; to: string | null };
  count: number;
  stands: BrandStand[];
  note?: string;
}

export interface Incident {
  kind: string;
  severity: "info" | "warning" | "critical";
  camera: string;
  ts: string;
  window: { from: string; to: string };
  evidence: string;
  clip_ref: { camera: string; from: string; to: string; review: string };
}

export interface InvestigationResponse {
  window: { from: string | null; to: string | null };
  kinds_available: string[];
  count: number;
  note?: string;
  incidents: Incident[];
}

export interface EventEnvelope {
  event_id: string;
  ts: string;
  type: string;
  camera: string | null;
  payload: Record<string, unknown>;
}

export interface EventsResponse {
  window: { from: string | null; to: string | null };
  count: number;
  limit: number;
  events: EventEnvelope[];
}

// ---- helpers ----

function qs(params: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

// ---- public API ----

export const getMetrics = (from?: string, to?: string) =>
  get<Metrics>(`/metrics${qs({ from, to })}`);

export const getFunnel = (from?: string, to?: string, granularity = "hour") =>
  get<Funnel>(`/funnel${qs({ from, to, granularity })}`);

export const getZones = (from?: string, to?: string) =>
  get<ZonesResponse>(`/zones${qs({ from, to })}`);

export const getAnomalies = (since?: string, kinds?: string) =>
  get<AnomaliesResponse>(`/anomaly${qs({ since, kinds })}`);

export const getEvents = (type?: string, limit = 20) =>
  get<EventsResponse>(`/events${qs({ type, limit })}`);

export const getInvestigation = (since?: string, kinds?: string) =>
  get<InvestigationResponse>(`/investigation${qs({ since, kinds })}`);

export const getBrands = (from?: string, to?: string) =>
  get<BrandsResponse>(`/brands${qs({ from, to })}`);

export const getCustomers = (from?: string, to?: string) =>
  get<CustomerSegments>(`/customers${qs({ from, to })}`);
