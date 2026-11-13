// "Luồng demo": suy tiến độ của luồng lõi ba bên CHỈ từ dữ liệu API thật (không có nút "đánh dấu xong",
// không gọi API thay người dùng). Mốc gốc (baseline) ghi lại lô/ngoại lệ đã có lúc bắt đầu luồng, nên "lô mới"
// là lô xuất hiện sau mốc đó — không cần thêm trường thời gian tạo ở backend.
import type { Benefit, ExceptionItem, Proposal, Role, Shipment } from './api'

export type StepKey = 'lot' | 'hold' | 'confirm' | 'start' | 'complete' | 'benefit' | 'incident'
export const MAIN_STEPS: StepKey[] = ['lot', 'hold', 'confirm', 'start', 'complete', 'benefit']

export interface FlowBaseline { startedAt: string; lotIds: string[]; excIds: string[]; lotId?: string | null }
export interface FlowData {
  shipments: Pick<Shipment, 'id' | 'status'>[]
  proposals: (Pick<Proposal, 'id' | 'status' | 'parties' | 'created_at'> & { shipment: Pick<Proposal['shipment'], 'id'> })[]
  benefits: Pick<Benefit, 'proposal_id'>[]
  exceptions: Pick<ExceptionItem, 'id' | 'exc_type' | 'status' | 'proposal_id'>[]
}
export interface FlowStep {
  key: StepKey; done: boolean
  role: Role            // người làm bước này (nút "Làm ở đây" mở cửa sổ của vai này)
  roles: Role[]         // các vai liên quan (hiện thành chip)
  route: string         // màn cần mở trong cửa sổ, có thể kèm query (vd "recommend?lot=…")
  waiting: Role[]       // bước xác nhận: vai còn chưa bấm
  org: string | null    // tổ chức của người làm bước này trong đề xuất (null = theo người của nhóm)
}
export interface FlowState { steps: FlowStep[]; incident: FlowStep; current: StepKey | null; lotId: string | null; proposalId: string | null }

const PARTY_ROLE: Record<string, Role> = { shipper: 'shipper', carrier: 'carrier', node: 'node_operator' }
const PARTY_ORDER = ['carrier', 'node', 'shipper'] // thứ tự xác nhận gợi ý (khớp DEMO_SCRIPT: Minh → Khôi → Nguyên)
/** Mức tiến của một đề xuất: proposed/expired/rejected/cancelled/replanned = 0 (chưa giữ chỗ hoặc đã rời luồng). */
const STAGE: Record<string, number> = { pending_acceptance: 2, confirmed: 3, executing: 4, completed: 5 }

/** Tổ chức tự đăng ký tên "<tên> · <vai>" (backend accounts.py) → tên đăng nhập của người đó; tổ chức mẫu → null (dùng người của nhóm). */
export function loginNameFor(org: string | null | undefined): string | null {
  const i = org ? org.lastIndexOf(' · ') : -1
  return org && i > 0 ? org.slice(0, i).trim() || null : null
}

export function baseline(data: Pick<FlowData, 'shipments' | 'exceptions'>, now = new Date()): FlowBaseline {
  return { startedAt: now.toISOString(), lotIds: data.shipments.map((s) => s.id), excIds: data.exceptions.map((e) => e.id), lotId: null }
}

/** Lô của luồng: lô theo dõi trước đó nếu vẫn còn hiệu lực, không thì lô mới đầu tiên chưa huỷ. */
export function pickLot(base: FlowBaseline, data: FlowData): string | null {
  const fresh = data.shipments.filter((s) => !base.lotIds.includes(s.id) && s.status !== 'cancelled')
  if (base.lotId && fresh.some((s) => s.id === base.lotId)) return base.lotId
  return fresh[0]?.id ?? null
}

/** Đề xuất "đang đại diện" cho lô: cái đi xa nhất trong luồng (đề xuất bị huỷ/hết hạn/ghép lại không tính). */
export function pickProposal(lotId: string | null, data: FlowData) {
  if (!lotId) return null
  const live = data.proposals.filter((p) => p.shipment.id === lotId && (STAGE[p.status] ?? 0) > 0)
  live.sort((a, b) => (STAGE[b.status] ?? 0) - (STAGE[a.status] ?? 0) || b.created_at.localeCompare(a.created_at))
  return live[0] ?? null
}

export function deriveFlow(base: FlowBaseline, data: FlowData): FlowState {
  const lotId = pickLot(base, data)
  const p = pickProposal(lotId, data)
  const stage = p ? STAGE[p.status] ?? 0 : 0
  const pid = p?.id ?? null
  const waiting = stage === 2 && p
    ? PARTY_ORDER.filter((k) => p.parties[k] && !p.parties[k].accepted).map((k) => PARTY_ROLE[k])
    : []
  const trip = pid ? `tracking?p=${pid}` : 'tracking'
  const orgOf = (r: Role) => (p ? p.parties[Object.keys(PARTY_ROLE).find((k) => PARTY_ROLE[k] === r) ?? '']?.org_name ?? null : null)
  const steps: FlowStep[] = [
    { key: 'lot', done: !!lotId, role: 'shipper', roles: ['shipper'], route: 'request', waiting: [], org: null },
    { key: 'hold', done: stage >= 2, role: 'shipper', roles: ['shipper'], route: lotId ? `recommend?lot=${lotId}` : 'recommend', waiting: [], org: null },
    { key: 'confirm', done: stage >= 3, role: waiting[0] ?? 'carrier', roles: ['carrier', 'node_operator', 'shipper'], route: 'confirm', waiting, org: orgOf(waiting[0] ?? 'carrier') },
    { key: 'start', done: stage >= 4, role: 'carrier', roles: ['carrier'], route: trip, waiting: [], org: orgOf('carrier') },
    { key: 'complete', done: stage >= 5, role: 'carrier', roles: ['carrier'], route: trip, waiting: [], org: orgOf('carrier') },
    { key: 'benefit', done: stage >= 5 && !!pid && data.benefits.some((b) => b.proposal_id === pid), role: 'shipper', roles: ['shipper'], route: 'benefits', waiting: [], org: null },
  ]
  // Thử sự cố (tuỳ chọn): một ngoại lệ BREAKDOWN mới (sau mốc gốc) đã được xử lý, vd bằng "Ghép lại".
  const breakdowns = data.exceptions.filter((e) => e.exc_type === 'BREAKDOWN' && !base.excIds.includes(e.id))
  const openOne = breakdowns.some((e) => e.status === 'open')
  const incident: FlowStep = {
    key: 'incident', done: breakdowns.some((e) => e.status === 'resolved'),
    role: openOne ? 'shipper' : 'carrier', roles: ['carrier', 'shipper'], route: openOne ? 'exceptions' : trip, waiting: [],
    org: openOne ? null : orgOf('carrier'),
  }
  const current = steps.find((s) => !s.done)?.key ?? null
  return { steps, incident, current, lotId, proposalId: pid }
}
