import { describe, expect, it } from 'vitest'
import { baseline, deriveFlow, loginNameFor, type FlowBaseline, type FlowData } from './demoFlow'

const parties = (s: boolean, c: boolean, n: boolean) => ({ shipper: { org_name: 'A', accepted: s }, carrier: { org_name: 'B', accepted: c }, node: { org_name: 'C', accepted: n } })
const prop = (id: string, lot: string, status: string, p = parties(false, false, false), created_at = '2026-11-13T10:00:00Z') => ({ id, status, parties: p, created_at, shipment: { id: lot } })
const OLD: FlowData = { shipments: [{ id: 'old', status: 'open' }], proposals: [], benefits: [], exceptions: [{ id: 'x0', exc_type: 'BREAKDOWN', status: 'resolved', proposal_id: 'p0' }] }
const BASE: FlowBaseline = baseline(OLD, new Date('2026-11-13T09:00:00Z'))
const withLot = (extra: Partial<FlowData> = {}): FlowData => ({ ...OLD, shipments: [...OLD.shipments, { id: 'new', status: 'open' }], ...extra })
const done = (d: FlowData) => Object.fromEntries(deriveFlow(BASE, d).steps.map((s) => [s.key, s.done]))

describe('Luồng demo: suy tiến độ từ dữ liệu API', () => {
  it('mốc gốc chưa có lô mới → bước hiện tại là Tạo lô', () => {
    const f = deriveFlow(BASE, OLD)
    expect(f.current).toBe('lot')
    expect(f.lotId).toBeNull()
    expect(f.steps.every((s) => !s.done)).toBe(true)
  })
  it('lô cũ có từ trước KHÔNG được tính là lô của luồng', () => {
    expect(deriveFlow(BASE, { ...OLD, proposals: [prop('p', 'old', 'completed')] }).current).toBe('lot')
  })
  it('có lô mới → bước Ghép + giữ slot, nút mở Ghép đúng lô', () => {
    const f = deriveFlow(BASE, withLot())
    expect(f.current).toBe('hold')
    expect(f.steps[1].route).toBe('recommend?lot=new')
  })
  it('đề xuất chỉ mới "proposed" (chưa giữ chỗ) chưa tính là xong bước giữ slot', () => {
    expect(deriveFlow(BASE, withLot({ proposals: [prop('p', 'new', 'proposed')] })).current).toBe('hold')
  })
  it('đang chờ xác nhận → liệt kê đúng vai còn thiếu, theo thứ tự vận tải → ICD → chủ hàng', () => {
    const f = deriveFlow(BASE, withLot({ proposals: [prop('p', 'new', 'pending_acceptance', parties(false, true, false))] }))
    expect(f.current).toBe('confirm')
    const step = f.steps.find((s) => s.key === 'confirm')!
    expect(step.waiting).toEqual(['node_operator', 'shipper'])
    expect(step.role).toBe('node_operator')
  })
  it('đi hết luồng: confirmed → executing → completed → có sổ lợi ích', () => {
    expect(deriveFlow(BASE, withLot({ proposals: [prop('p', 'new', 'confirmed')] })).current).toBe('start')
    expect(deriveFlow(BASE, withLot({ proposals: [prop('p', 'new', 'executing')] })).current).toBe('complete')
    const c = withLot({ proposals: [prop('p', 'new', 'completed')] })
    expect(deriveFlow(BASE, c).current).toBe('benefit')
    expect(deriveFlow(BASE, c).steps[3].route).toBe('tracking?p=p')
    const all = deriveFlow(BASE, { ...c, benefits: [{ proposal_id: 'p' }] })
    expect(all.current).toBeNull()
    expect(all.steps.every((s) => s.done)).toBe(true)
  })
  it('sổ lợi ích của chuyến KHÁC không làm xong bước lợi ích', () => {
    expect(done(withLot({ proposals: [prop('p', 'new', 'completed')], benefits: [{ proposal_id: 'other' }] })).benefit).toBe(false)
  })
  it('hold hết hạn → quay lại bước giữ slot (không giữ dấu xong cũ)', () => {
    expect(deriveFlow(BASE, withLot({ proposals: [prop('p', 'new', 'expired')] })).current).toBe('hold')
  })
  it('lô bị huỷ → quay lại bước Tạo lô; có lô mới khác thì theo lô đó', () => {
    const cancelled = { ...OLD, shipments: [...OLD.shipments, { id: 'new', status: 'cancelled' }] }
    expect(deriveFlow({ ...BASE, lotId: 'new' }, cancelled).current).toBe('lot')
    const other = { ...cancelled, shipments: [...cancelled.shipments, { id: 'new2', status: 'open' }] }
    expect(deriveFlow({ ...BASE, lotId: 'new' }, other).lotId).toBe('new2')
  })
  it('giữ lô đang theo dõi dù có thêm lô mới khác', () => {
    const two = { ...withLot(), shipments: [...withLot().shipments, { id: 'a-first', status: 'open' }] }
    expect(deriveFlow({ ...BASE, lotId: 'new' }, two).lotId).toBe('new')
  })
  it('ghép lại sau sự cố: đề xuất cũ "replanned" bị bỏ qua, đề xuất mới quyết định tiến độ', () => {
    const d = withLot({ proposals: [prop('old-p', 'new', 'replanned', parties(true, true, true)), prop('p2', 'new', 'pending_acceptance', parties(false, false, false), '2026-11-13T11:00:00Z')] })
    const f = deriveFlow(BASE, d)
    expect(f.proposalId).toBe('p2')
    expect(f.current).toBe('confirm')
  })
  it('đề xuất đi xa nhất được chọn khi lô có nhiều đề xuất', () => {
    const d = withLot({ proposals: [prop('a', 'new', 'cancelled'), prop('b', 'new', 'executing'), prop('c', 'new', 'expired')] })
    expect(deriveFlow(BASE, d).proposalId).toBe('b')
  })
  it('Thử sự cố: BREAKDOWN có từ trước không tính; mới + đang mở → sang Ngoại lệ của chủ hàng; đã xử lý → xong', () => {
    expect(deriveFlow(BASE, withLot()).incident.done).toBe(false)
    const open = deriveFlow(BASE, withLot({ exceptions: [...OLD.exceptions, { id: 'x1', exc_type: 'BREAKDOWN', status: 'open', proposal_id: 'p' }] })).incident
    expect(open).toMatchObject({ done: false, role: 'shipper', route: 'exceptions' })
    const fixed = deriveFlow(BASE, withLot({ exceptions: [{ id: 'x1', exc_type: 'BREAKDOWN', status: 'resolved', proposal_id: 'p' }] })).incident
    expect(fixed.done).toBe(true)
    expect(deriveFlow(BASE, withLot({ exceptions: [{ id: 'x2', exc_type: 'DELAY_RISK', status: 'resolved', proposal_id: 'p' }] })).incident.done).toBe(false)
  })
  it('bên còn thiếu thuộc tổ chức tự đăng ký → mở đúng người đó; tổ chức mẫu → người của nhóm', () => {
    const p = { shipper: { org_name: 'Công ty Hàng hóa A (Shipper)', accepted: true }, carrier: { org_name: 'QA Perf Xe 0 · Nhà vận tải', accepted: false }, node: { org_name: 'ICD Cảng C (Node)', accepted: false } }
    const f = deriveFlow(BASE, withLot({ proposals: [prop('p', 'new', 'pending_acceptance', p)] }))
    const step = f.steps.find((s) => s.key === 'confirm')!
    expect(step.org).toBe('QA Perf Xe 0 · Nhà vận tải')
    expect(loginNameFor(step.org)).toBe('QA Perf Xe 0')
    expect(loginNameFor('ICD Cảng C (Node)')).toBeNull()
    expect(loginNameFor(null)).toBeNull()
    expect(deriveFlow(BASE, withLot({ proposals: [prop('p', 'new', 'confirmed', p)] })).steps[3].org).toBe('QA Perf Xe 0 · Nhà vận tải')
  })
})
