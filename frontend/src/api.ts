// Client API. Hợp đồng lấy từ OpenAPI của FastAPI (backend/app/schemas.py).
export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export type UserKey = 'shipper_a' | 'carrier_b' | 'node_c' | 'dispatch'

export const DEMO_USERS: { key: UserKey; role: 'shipper' | 'carrier' | 'node_operator' | 'dispatcher' }[] = [
  { key: 'shipper_a', role: 'shipper' },
  { key: 'carrier_b', role: 'carrier' },
  { key: 'node_c', role: 'node_operator' },
  { key: 'dispatch', role: 'dispatcher' },
]

export interface Me { user_id: string; user_name: string; org_id: string; org_name: string; org_type: string; role: string }
export interface Meta { data_mode: 'mock' | 'live'; is_simulated: boolean; server_time: string; stale_position_minutes: number }
export interface Location { id: string; name: string; kind: string; lat: number; lng: number }
export interface Shipment {
  id: string; tenant_id: string; code: string; cargo_type: string; weight_kg: number | null; volume_m3: number | null
  origin_location_id: string; dest_location_id: string; ready_at: string; pickup_deadline: string | null
  cutoff_at: string | null; status: string; is_simulated: boolean; version: number; data_updated_at: string
  price_vnd: number | null; customer_name: string | null; missing_fields: string[]
}
export interface Vehicle {
  id: string; tenant_id: string; plate: string; cargo_types: string[]; capacity_kg: number; capacity_m3: number
  status: string; position_updated_at: string | null; is_simulated: boolean
}
export interface Slot {
  id: string; node_org_id: string; location_id: string; start_at: string; end_at: string
  capacity: number; remaining: number; source: string; is_simulated: boolean
}
export interface GateItem { gate: string; status: 'PASS' | 'FAIL' | 'UNKNOWN'; reason_code: string; detail: Record<string, unknown> }
export interface Rejection { vehicle_id: string; plate: string; status: 'FAIL' | 'UNKNOWN'; reasons: GateItem[] }
export interface Proposal {
  id: string; status: string; version: number; is_simulated: boolean; confirmation_source: string | null
  shipment: Pick<Shipment, 'id' | 'code' | 'cargo_type' | 'weight_kg' | 'volume_m3' | 'ready_at' | 'pickup_deadline' | 'cutoff_at' | 'origin_location_id' | 'dest_location_id' | 'status'>
  vehicle: { id: string; plate: string; capacity_kg: number; capacity_m3: number; carrier_org_name: string | null }
  slot: { id: string; start_at: string; end_at: string; remaining: number; capacity: number; source: string; node_org_name: string | null } | null
  score: number | null
  score_components: { fit: number; time_margin: number; empty_km_saved: number; weights: Record<string, number>; missing: string[] }
  estimated_saving_vnd: number | null; deadhead_km: number | null
  eta: { pickup: string; method: string; confidence: string } | null
  gates: GateItem[]; rejections: Rejection[]
  rule_version: string; model_version: string; assumption_version: string
  expires_at: string | null; hold_seconds_left: number | null
  parties: Record<string, { org_name: string | null; accepted: boolean }>
  my_actions: { hold: boolean; accept: boolean; reject: boolean }
  run_id: string | null; created_at: string
}
export interface MatchRun {
  run_id: string; status: 'proposals' | 'no_feasible_option' | 'needs_data'; proposals: Proposal[]
  rejections: Rejection[]; needs_data: Rejection[]; rule_version: string; assumption_version: string
  generated_at: string; evaluated_vehicles: number; eta_method: string
}
export interface ShipmentCreate {
  code: string; cargo_type: string; weight_kg: number; volume_m3: number; origin_location_id: string
  dest_location_id: string; ready_at: string; pickup_deadline: string; cutoff_at: string
  price_vnd?: number | null; customer_name?: string | null
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public reasons: GateItem[] = []) {
    super(message)
  }
}

let currentUser: UserKey = (() => {
  try { return (localStorage.getItem('pivot.user') as UserKey) || 'shipper_a' } catch { return 'shipper_a' }
})()
export const getUser = () => currentUser
export function setUser(u: UserKey) {
  currentUser = u
  try { localStorage.setItem('pivot.user', u) } catch { /* localStorage có thể bị chặn */ }
}

async function request<T>(path: string, init: RequestInit & { idem?: string } = {}): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer dev:${currentUser}`,
    ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    ...(init.idem ? { 'Idempotency-Key': init.idem } : {}),
  }
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Cannot reach the API')
  }
  if (!res.ok) {
    let body: unknown = null
    try { body = await res.json() } catch { /* không phải JSON */ }
    const d = (body as { detail?: unknown } | null)?.detail
    if (d && typeof d === 'object' && !Array.isArray(d)) {
      const o = d as { code?: string; message?: string; reasons?: GateItem[] }
      throw new ApiError(res.status, o.code ?? `HTTP_${res.status}`, o.message ?? res.statusText, o.reasons ?? [])
    }
    if (Array.isArray(d)) { // lỗi validate 422 của FastAPI
      const first = d[0] as { loc?: string[]; msg?: string } | undefined
      throw new ApiError(res.status, 'VALIDATION', `${(first?.loc ?? []).slice(1).join('.')}: ${first?.msg ?? 'invalid'}`)
    }
    throw new ApiError(res.status, `HTTP_${res.status}`, typeof d === 'string' ? d : res.statusText)
  }
  return res.json() as Promise<T>
}

const post = <T,>(path: string, body: unknown, idem?: string) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body), idem })

export const api = {
  me: () => request<Me>('/v1/me'),
  meta: () => request<Meta>('/v1/meta'),
  locations: () => request<Location[]>('/v1/locations'),
  shipments: () => request<Shipment[]>('/v1/shipments'),
  vehicles: () => request<Vehicle[]>('/v1/vehicles'),
  slots: () => request<Slot[]>('/v1/slots'),
  createShipment: (b: ShipmentCreate) => post<Shipment>('/v1/shipments', b),
  match: (shipment_id: string) => post<MatchRun>('/v1/match-runs', { shipment_id }),
  proposals: () => request<Proposal[]>('/v1/proposals'),
  act: (p: Pick<Proposal, 'id' | 'version'>, action: 'hold' | 'accept' | 'reject') =>
    post<Proposal>(`/v1/proposals/${p.id}/${action}`, { version: p.version }, crypto.randomUUID()),
  retime: () => post<{ retimed_by_seconds: number }>('/v1/demo/retime', {}),
}
