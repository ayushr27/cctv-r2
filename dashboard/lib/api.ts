// Typed client for the Store Intelligence API.
// Reads NEXT_PUBLIC_API_URL (default http://localhost:8000). Every call is
// cache: 'no-store' so the polling pages always see fresh data.

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export const API_BASE = BASE;

// ---- response types ----

export interface Clip {
  camera: string;
  available: boolean;
  video_url: string;
  start_s: number;
  end_s: number;
}

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
  camera?: string | null;
  clip?: Clip | null;
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
  clip_ref: {
    camera: string;
    from: string;
    to: string;
    review: string;
    available?: boolean;
    video_url?: string;
    start_s?: number;
    end_s?: number;
  };
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

// ---- PDF contract layer (/stores/{id}/*) ----

export const STORES = [
  { id: "ALL", label: "All stores" },
  { id: "STORE_BLR_002", label: "Store 1 — Brigade Road" },
  { id: "STORE_BLR_009", label: "Store 2 — Pink uniform" },
];

// Default store for the global switcher: the cumulative view.
export const DEFAULT_STORE = "ALL";

export function storeLabel(id: string): string {
  return STORES.find((s) => s.id === id)?.label ?? id;
}

export interface StoreMetrics {
  store_id: string;
  window: { from: string | null; to: string | null };
  unique_visitors: number;
  peak_occupancy: number;
  total_visitors: number;
  door_entries: number;
  zone_visitors: number;
  staff_excluded: number;
  conversion_rate: number;
  converted_visitors: number;
  conversion_method: string;
  observed_checkouts: number | null;
  avg_dwell_ms: number;
  avg_dwell_per_zone_ms: Record<string, number>;
  queue_depth_max: number;
  abandonment_rate: number;
  billing_queue_joins: number;
  billing_queue_abandons: number;
  demographics: {
    gender: Record<string, number>;
    age_bucket: Record<string, number>;
    note: string;
  };
  data_confidence: string;
  conversion_evidence: string;
}

export interface StoreFunnel {
  store_id: string;
  stages: { stage: string; count: number; drop_off: number }[];
  sessions: number;
  data_confidence: string;
}

export interface HeatZone {
  zone_id: string;
  visits: number;
  avg_dwell_ms: number;
  visit_score: number;
  dwell_score: number;
}

export interface StoreHeatmap {
  store_id: string;
  zones: HeatZone[];
  sessions: number;
  data_confidence: string;
}

export interface StoreAnomaly {
  type: string;
  severity: "INFO" | "WARN" | "CRITICAL";
  observed?: number;
  zone_id?: string;
  evidence: string;
  suggested_action: string;
}

export interface StoreAnomaliesResponse {
  store_id: string;
  count: number;
  anomalies: StoreAnomaly[];
}

export const getStoreMetrics = (id: string, from?: string, to?: string) =>
  get<StoreMetrics>(`/stores/${id}/metrics${qs({ from, to })}`);

export const getStoreFunnel = (id: string, from?: string, to?: string) =>
  get<StoreFunnel>(`/stores/${id}/funnel${qs({ from, to })}`);

export const getStoreHeatmap = (id: string, from?: string, to?: string) =>
  get<StoreHeatmap>(`/stores/${id}/heatmap${qs({ from, to })}`);

export const getStoreAnomalies = (id: string, since?: string) =>
  get<StoreAnomaliesResponse>(`/stores/${id}/anomalies${qs({ since })}`);

// ---- rich store-aware views (Live / Brands / Customers / Investigation) ----

export interface StoreRecentEvent {
  ts: string;
  type: string;
  camera: string | null;
  visitor: string;
  zone: string | null;
  store_id: string;
}

export interface StoreLive {
  store_id: string;
  window: { from: string | null; to: string | null };
  footfall: number;
  peak_occupancy: number;
  total_visitors: number;
  door_entries: number;
  zone_visitors: number;
  staff_count: number;
  conversion_rate: number;
  conversion_method: string;
  observed_checkouts: number | null;
  has_pos: boolean;
  avg_dwell_ms: number;
  queue_depth_max: number;
  total_revenue: number | null;
  avg_bill_value: number | null;
  peak_hour: string | null;
  demographics: { gender: Record<string, number>; age_bucket: Record<string, number>; note: string };
  recent_events: StoreRecentEvent[];
  data_confidence: string;
}

export interface StoreBrandStand {
  stand: string;
  label: string;
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

export interface StoreBrands {
  store_id: string;
  window: { from: string | null; to: string | null };
  count: number;
  stands: StoreBrandStand[];
  data_confidence: string;
  note: string | null;
}

export interface StoreCustomers {
  store_id: string;
  window: { from: string | null; to: string | null };
  shopping_party: { solo: number; group: number; entry_detected: number; group_rate: number; basis: string };
  customers: { unique: number; repeat: number; repeat_rate: number; basis: string };
  basket: {
    bills: number;
    avg_items_per_bill: number;
    avg_value_per_bill: number;
    single_brand_bills: number;
    multi_brand_bills: number;
    avg_brands_per_bill: number;
  };
  note: string | null;
}

export interface StoreIncident {
  kind: string;
  severity: "info" | "warning" | "critical";
  camera: string;
  ts: string;
  window: { from: string; to: string };
  evidence: string;
  clip_ref: {
    camera: string;
    from: string;
    to: string;
    review: string;
    available?: boolean;
    video_url?: string;
    start_s?: number;
    end_s?: number;
  };
}

export interface StoreInvestigation {
  store_id: string;
  window: { from: string | null; to: string | null };
  count: number;
  kinds_available: string[];
  incidents: StoreIncident[];
  note: string;
}

export const getStoreLive = (id: string, from?: string, to?: string) =>
  get<StoreLive>(`/stores/${id}/live${qs({ from, to })}`);

export const getStoreBrands = (id: string, from?: string, to?: string) =>
  get<StoreBrands>(`/stores/${id}/brands${qs({ from, to })}`);

export const getStoreCustomers = (id: string, from?: string, to?: string) =>
  get<StoreCustomers>(`/stores/${id}/customers${qs({ from, to })}`);

export const getStoreInvestigation = (id: string, since?: string) =>
  get<StoreInvestigation>(`/stores/${id}/investigation${qs({ since })}`);
