// Client API. Hợp đồng lấy từ OpenAPI của FastAPI (backend/app/schemas.py).
export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export type Role = 'shipper' | 'carrier' | 'node_operator' | 'dispatcher'
export const ROLES: Role[] = ['shipper', 'carrier', 'node_operator', 'dispatcher']
export interface Session { token: string; name: string; role: Role }
export interface LoginResult { token: string; is_new: boolean; me: Me }

export interface Me { user_id: string; user_name: string; org_id: string; org_name: string; org_type: string; role: string }
export interface Meta { data_mode: 'mock' | 'live'; is_simulated: boolean; server_time: string; stale_position_minutes: number; stale_shipment_minutes?: number; admin_key_required: boolean; image_intake_enabled?: boolean; pdf_intake_enabled?: boolean }
export interface Location { id: string; name: string; kind: string; lat: number; lng: number }
export interface Shipment {
  id: string; tenant_id: string; code: string; cargo_type: string; weight_kg: number | null; volume_m3: number | null
  origin_location_id: string; dest_location_id: string; ready_at: string; pickup_deadline: string | null
  cutoff_at: string | null; status: string; is_simulated: boolean; version: number; data_updated_at: string
  price_vnd: number | null; customer_name: string | null; missing_fields: string[]
}
export type VehicleState = 'empty' | 'reserved' | 'executing' | 'offline' | 'window_expired' | 'free_later' | 'no_window'
export interface Vehicle {
  id: string; tenant_id: string; plate: string; cargo_types: string[]; capacity_kg: number; capacity_m3: number
  status: string; position_updated_at: string | null; is_simulated: boolean
  yard: { id: string; name: string; kind: string; lat: number; lng: number } | null // bãi đang đậu
  free_from: string | null; free_to: string | null
  availability: { state: VehicleState; reason: string } | null
  position_age_seconds: number | null
  distance_to_target_km: number | null; distance_method: 'estimate' | null // ƯỚC TÍNH (đường chim bay × hệ số đường bộ)
  deadhead_eta: { minutes: number; p50: string; p90: string; method: string } | null
}
export interface FleetRefresh { updated: number; window_extended: number; already_fresh: number; skipped: Record<string, number>; at: string; is_simulated: boolean }
export interface Slot {
  id: string; node_org_id: string; node_org_name: string | null; location_id: string; start_at: string; end_at: string
  capacity: number; remaining: number; source: string; is_simulated: boolean
}
export interface GateItem { gate: string; status: 'PASS' | 'FAIL' | 'UNKNOWN'; reason_code: string; detail: Record<string, unknown> }
export interface Rejection { vehicle_id: string; plate: string; status: 'FAIL' | 'UNKNOWN'; reasons: GateItem[]; yard?: string | null; yard_km?: number | null }
export interface Proposal {
  id: string; status: string; version: number; is_simulated: boolean; confirmation_source: string | null
  shipment: Pick<Shipment, 'id' | 'code' | 'cargo_type' | 'weight_kg' | 'volume_m3' | 'ready_at' | 'pickup_deadline' | 'cutoff_at' | 'origin_location_id' | 'dest_location_id' | 'status'>
  vehicle: { id: string; plate: string; capacity_kg: number; capacity_m3: number; carrier_org_name: string | null; yard?: string | null }
  slot: { id: string; start_at: string; end_at: string; remaining: number; capacity: number; source: string; node_org_name: string | null } | null
  score: number | null
  score_components: { fit: number; time_margin: number; empty_km_saved: number; weights: Record<string, number>; missing: string[] }
  estimated_saving_vnd: number | null; deadhead_km: number | null
  eta: { pickup: string; pickup_p90?: string; icd?: string; icd_p90?: string; method: string; confidence: string; cutoff_risk_p90?: boolean } | null
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
  price_vnd?: number | null; customer_name?: string | null; draft_id?: string | null
}
export type ShipmentUpdate = Partial<Omit<ShipmentCreate, 'code' | 'draft_id'>> & { version: number }
export interface IntakeField { value: unknown; display: string | null; source: { quote: string; start: number; end: number } | null; status: 'ok' | 'needs_review'; notes: string[] }
export interface IntakeDraft {
  draft_id: string; extractor: { name: string; kind: string; note?: string }; source: { length: number; sha256: string; kind?: 'image' | 'pdf_text' | 'pdf_scan'; pages?: number }; reference_time: string
  fields: Record<string, IntakeField>; needs_review: string[]; complete: boolean; suspicious_instructions: boolean; multiple_shipments?: boolean; looks_like_request?: boolean; is_draft_only: boolean
  transcript?: string | null; image_quota_remaining?: number | null
}

export interface TimelineItem {
  at: string; kind: 'match' | 'decision' | 'event' | 'exception' | 'benefit'; code: string; actor: string | null
  quality: string | null; latency_s: number | null; detail: Record<string, unknown>
}
export interface Timeline { proposal_id: string; status: string; version: number; shipment_code: string; items: TimelineItem[] }
export interface Replay {
  proposal_id: string; stored_score: number | null; recomputed_score: number; reproducible: boolean; weights_sum: number | null
  all_gates_pass: boolean; gate_count: number; rejected_candidates: number; rule_version: string; model_version: string
  assumption_version: string; run_id: string | null; baseline: { id: string; empty_km: number; cost_per_km_vnd: number; fixed_at: string } | null
  snapshot_keys: string[]
}
export type Severity = 'low' | 'medium' | 'high' | 'critical'
export interface ExceptionTask { id: string; step_key: string; kind: 'auto' | 'human'; owner: string; status: 'pending' | 'done'; completed_by: string | null; can_complete: boolean }
export interface ExceptionItem {
  id: string; proposal_id: string; exc_type: string; status: 'open' | 'resolved'; created_at: string
  detail: { action?: string; delay_minutes?: number; resolution?: string; note?: string; resolved_by?: string }
  severity: Severity; sla_due_at: string | null; escalated_at: string | null; overdue: boolean; source: string
  shipment_code: string; plate: string; proposal_status: string; proposal_version: number
  tasks: ExceptionTask[]; can_replan: boolean; rule_version: string | null
}
export interface NotificationItem { id: string; exception_id: string | null; channel: 'in_app' | 'sms_sim' | 'email_sim'; created_at: string; read: boolean
  payload: { category: string; severity: Severity; shipment_code: string; plate: string; escalated?: boolean } }
export interface NotificationList { unread: number; items: NotificationItem[] }
export interface Benefit {
  id: string; proposal_id: string | null; shipment_code: string; vehicle_plate: string; cost_category: string
  quantity_before: number; quantity_after: number; unit: string; unit_rate: number; currency: string; net_vnd: number
  status: 'estimated' | 'measured' | 'verified'; baseline_id: string; assumption_version: string
  beneficiary_org_name: string | null; verifier: string | null; verified_at: string | null; can_verify: boolean; verifier_independent_available: boolean; is_simulated: boolean
  evidence: { id: string; event_type: string; source_system: string; occurred_at: string; received_at: string; quality_status: string; payload: Record<string, unknown> }[]
  baseline: { id: string; empty_km: number; cost_per_km_vnd: number; fixed_at: string } | null
  assumptions: Record<string, unknown>; formula: { before: number; after: number; rate: number } | null
}
export interface BenefitList { items: Benefit[]; totals: Record<'estimated' | 'measured' | 'verified', { count: number; net_vnd: number }> }
export interface ScenarioResult { id: string; passed: boolean; steps: { label: string; ok: boolean; detail: string }[]; open: string | null }
export type SimMode = 'normal' | 'slow' | 'breakdown' | 'detour'
export interface LiveEta {
  method: string; confidence: string; p50?: string | null; p90?: string | null; icd?: string; icd_p90?: string
  stalled?: boolean; cutoff_risk?: boolean; cutoff_risk_p90?: boolean; remaining_km?: number; speed_kmh?: number
}
export interface EtaModel {
  label: string; trained: boolean; status: 'promoted' | 'forced' | 'rule_fallback' | 'untrained'; reason: string; note: string
  source?: 'onnx' | 'sim'; forced?: boolean; baseline?: string | null; sha256?: string | null
  metrics: { n_train: number | null; n_test: number | null; mae_rule: number; mae_ml: number; improvement_pct: number; within15_rule: number; within15_ml: number
    p90_coverage_rule: number; p90_coverage_ml: number; min_improvement_pct: number; coverage_target: number[]; drift: number } | null
}
export interface EtaSignals {
  status: 'ok' | 'partial' | 'fallback' | 'disabled'; method: string; version: string; confidence?: string; reason?: string
  p50?: string | null; p90?: string | null; minutes_p50?: number; minutes_p90?: number; band?: string
  sources?: { route: string | null; weather: string | null; traffic?: string | null }
  components?: { road_km: number; free_flow_min: number; remaining_fraction: number; truck_factor: number; traffic_factor: number; traffic_kind?: 'live' | 'rule'; weather_factor: number }
  traffic?: { live_min: number; typical_min: number; share: Record<string, number>; segments: { level: string; points: [number, number][] }[]; fetched_at: string; source: string } | null
  weather?: { precip_mm_h: number; weather_code: number; wind_kmh: number; observed_at?: string | null; source: string } | null
}
export interface TripTrack {
  proposal_id: string; status: string; shipment_code: string; plate: string; is_simulated: boolean
  position: { lat: number; lng: number; speed_kmh: number | null; age_seconds: number | null } | null
  progress_pct: number; remaining_km: number; total_km: number
  milestones: { code: string; reached: boolean }[]
  eta: LiveEta | null; eta_ml: { p50_minutes: number; p90_minutes: number; label: string; confidence: string } | null; cutoff_at: string | null
  route: { lat: number; lng: number }[]; pickup_index: number; route_source: 'osrm' | 'simulated'; eta_signals?: EtaSignals | null
  geofences: { code: string; lat: number; lng: number; radius_m: number }[]
  track?: { at: string; lat: number; lng: number; speed_kmh: number | null }[]
}
export interface DockAppt {
  id: string; proposal_id: string; dock_id: string; dock_code: string; status: 'scheduled' | 'checked_in' | 'unloading' | 'completed' | 'no_show' | 'cancelled'
  window_start: string; window_end: string; eta_at: string | null; checked_in_at: string | null; dwell_minutes: number | null; version: number
  shipment_code: string; plate: string; late_minutes: number
  suggestion: { dock_code: string | null; window_start: string; window_end: string; reason: string } | null
  can_reschedule: boolean; can_accept_suggestion: boolean; can_check_in: boolean; can_start: boolean; can_complete: boolean
}
export interface DockBoard {
  docks: { id: string; code: string; node_org_name: string | null; handling_minutes: number }[]
  appointments: DockAppt[]; busy: { dock_id: string; window_start: string; window_end: string }[]
  kpis: { dock_count: number; utilization_pct: number; queue: number; no_show: number; avg_dwell_minutes: number | null; scheduled: number }
}
export const SCENARIO_IDS = ['success', 'incompatible', 'stale', 'race', 'eta_change', 'duplicate_restart', 'tracking', 'breakdown_replan', 'dock', 'eta_model'] as const

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public reasons: GateItem[] = []) {
    super(message)
  }
}

// Phiên đăng nhập lưu ở sessionStorage → MỖI TAB MỘT NGƯỜI (mở tab mới là chưa đăng nhập). Ngôn ngữ vẫn ở localStorage.
// Chế độ nhúng (`?embed=1`): ứng dụng chạy trong một cửa sổ của không gian nhiều cửa sổ; phiên chỉ nằm trong bộ nhớ của khung
// (trang bao ngoài đưa token vào qua postMessage) vì sessionStorage được chia sẻ giữa các khung cùng nguồn gốc.
export const EMBED = typeof location !== 'undefined' && new URLSearchParams(location.search).get('embed') === '1'
let session: Session | null = (() => {
  if (EMBED) return null
  try { const raw = sessionStorage.getItem('pivot.session'); return raw ? (JSON.parse(raw) as Session) : null } catch { return null }
})()
export const getSession = () => session
export function setSession(s: Session | null) {
  session = s
  if (EMBED) return
  try { s ? sessionStorage.setItem('pivot.session', JSON.stringify(s)) : sessionStorage.removeItem('pivot.session') } catch { /* sessionStorage có thể bị chặn */ }
}
let onUnauthorized: (() => void) | null = null
export const setOnUnauthorized = (fn: (() => void) | null) => { onUnauthorized = fn }

// Mã quản trị (chỉ cần khi triển khai công khai): giữ trong sessionStorage — đóng tab là mất, không lưu lâu dài.
let adminKey = (() => { try { return sessionStorage.getItem('pivot.adminKey') ?? '' } catch { return '' } })()
export const getAdminKey = () => adminKey
export function setAdminKey(k: string) {
  adminKey = k.trim()
  try { adminKey ? sessionStorage.setItem('pivot.adminKey', adminKey) : sessionStorage.removeItem('pivot.adminKey') } catch { /* bỏ qua */ }
}

async function request<T>(path: string, init: RequestInit & { idem?: string } = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(session ? { Authorization: `Bearer dev:${session.token}` } : {}),
    ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    ...(init.idem ? { 'Idempotency-Key': init.idem } : {}),
    ...(adminKey && path.startsWith('/v1/demo/') ? { 'X-Admin-Key': adminKey } : {}),
  }
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Cannot reach the API')
  }
  if (res.status === 401 && session && !path.startsWith('/v1/auth/')) { // phiên không còn hợp lệ (vd dữ liệu đã reset)
    setSession(null)
    onUnauthorized?.()
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
  login: (name: string, role: Role) => post<LoginResult>('/v1/auth/login', { name, role }),
  me: () => request<Me>('/v1/me'),
  meta: () => request<Meta>('/v1/meta'),
  locations: () => request<Location[]>('/v1/locations'),
  shipments: () => request<Shipment[]>('/v1/shipments'),
  vehicles: (toLocationId?: string) => request<Vehicle[]>(`/v1/vehicles${toLocationId ? `?to_location_id=${toLocationId}` : ''}`),
  refreshFleet: () => post<FleetRefresh>('/v1/vehicles/refresh-fleet', {}),
  slots: () => request<Slot[]>('/v1/slots'),
  createShipment: (b: ShipmentCreate) => post<Shipment>('/v1/shipments', b),
  updateShipment: (id: string, b: ShipmentUpdate) => request<Shipment>(`/v1/shipments/${id}`, { method: 'PATCH', body: JSON.stringify(b) }),
  refreshShipment: (id: string) => post<Shipment>(`/v1/shipments/${id}/refresh`, {}),
  cancelShipment: (id: string) => request<Shipment>(`/v1/shipments/${id}`, { method: 'DELETE' }),
  intakeDraft: (text: string) => post<IntakeDraft>('/v1/intake/drafts', { text }),
  intakeFile: (file_base64: string) => post<IntakeDraft>('/v1/intake/drafts/file', { file_base64 }), // PDF hoặc ảnh
  sendVehicleEvent: (vehicleId: string, event_type: 'VEHICLE_POSITION', payload: Record<string, unknown> = {}) =>
    post<{ event_id: string; duplicate: boolean }>('/v1/events', {
      entity_type: 'vehicle', entity_id: vehicleId, event_type, payload, occurred_at: new Date().toISOString(),
      source_system: 'ui-carrier', source_event_id: crypto.randomUUID(),
    }),
  match: (shipment_id: string, node_org_id?: string) => post<MatchRun>('/v1/match-runs', { shipment_id, node_org_id: node_org_id || null }),
  proposals: () => request<Proposal[]>('/v1/proposals'),
  act: (p: Pick<Proposal, 'id' | 'version'>, action: 'hold' | 'accept' | 'reject') =>
    post<Proposal>(`/v1/proposals/${p.id}/${action}`, { version: p.version }, crypto.randomUUID()),
  timeline: (id: string) => request<Timeline>(`/v1/proposals/${id}/timeline`),
  replay: (id: string) => request<Replay>(`/v1/proposals/${id}/replay`),
  exceptions: () => request<ExceptionItem[]>('/v1/exceptions'),
  resolve: (id: string, resolution: 'accept_delay' | 'request_replan', note?: string) =>
    post<ExceptionItem>(`/v1/exceptions/${id}/resolve`, { resolution, note }),
  sendEvent: (entity_id: string, event_type: string, payload: Record<string, unknown> = {}) =>
    post<{ event_id: string; duplicate: boolean }>('/v1/events', {
      entity_id, event_type, payload, occurred_at: new Date().toISOString(), source_system: 'ui-carrier', source_event_id: crypto.randomUUID(),
    }),
  tracking: () => request<TripTrack[]>('/v1/tracking'),
  trip: (id: string) => request<TripTrack>(`/v1/tracking/${id}`),
  roadRoute: (id: string) => post<{ route_source: 'osrm' | 'simulated'; distance_km: number | null; duration_min: number | null }>(`/v1/tracking/${id}/road-route`, {}),
  simStart: (id: string) => post<{ running: boolean; mode: SimMode }>(`/v1/sim/${id}/start`, {}),
  simMode: (id: string, mode: SimMode) => post<{ running: boolean; mode: SimMode }>(`/v1/sim/${id}/mode`, { mode }),
  completeTask: (exId: string, taskId: string) => post<ExceptionItem>(`/v1/exceptions/${exId}/tasks/${taskId}/complete`, {}),
  replan: (p: { id: string; version: number }) =>
    post<{ cancelled_proposal_id: string; shipment_id: string; new_proposals: number }>(`/v1/proposals/${p.id}/replan`, { version: p.version }),
  notifications: () => request<NotificationList>('/v1/notifications'),
  readNotifications: () => post<{ ok: boolean }>('/v1/notifications/read', {}),
  dockBoard: () => request<DockBoard>('/v1/docks/board'),
  dockReschedule: (id: string, version: number, window_start: string, dock_id: string) => post<unknown>(`/v1/dock-appointments/${id}/reschedule`, { version, window_start, dock_id }),
  dockAccept: (id: string, version: number) => post<unknown>(`/v1/dock-appointments/${id}/accept-suggestion`, { version }),
  etaModel: () => request<EtaModel>('/v1/eta/model'),
  etaTrain: (drift: number) => post<EtaModel>('/v1/eta/train', { drift }),
  benefits: () => request<BenefitList>('/v1/benefits'),
  benefit: (id: string) => request<Benefit>(`/v1/benefits/${id}`),
  verify: (id: string) => post<Benefit>(`/v1/benefits/${id}/verify`, {}),
  runScenario: (id: string) => post<ScenarioResult>(`/v1/demo/scenarios/${id}/run`, {}),
  retime: () => post<{ retimed_by_seconds: number }>('/v1/demo/retime', {}),
}
