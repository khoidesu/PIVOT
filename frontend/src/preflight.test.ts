import { describe, expect, it } from 'vitest'
import type { Shipment, Vehicle } from './api'
import { preflight } from './preflight'

const NOW = Date.parse('2026-11-12T10:00:00Z')
const iso = (minFromNow: number) => new Date(NOW + minFromNow * 60000).toISOString()
const lot = (o: Partial<Shipment> = {}) => ({ data_updated_at: iso(-5), pickup_deadline: iso(120), cutoff_at: iso(600), ...o }) as Shipment
const veh = (posAgeMin: number, status = 'available') => ({ status, position_updated_at: iso(-posAgeMin) }) as Vehicle

describe('preflight (BUG-04)', () => {
  it('dữ liệu tươi, mốc tương lai → không cảnh báo', () => {
    const p = preflight(lot(), [veh(1), veh(2)], NOW, 60, 5)
    expect(p).toMatchObject({ lotStale: false, pickupPassed: false, cutoffPassed: false, gpsStale: 0, gpsTotal: 2 })
  })
  it('ảnh #5: lô 1.773 phút, deadline/cut-off đã qua → tách "cũ" khỏi "đã qua"', () => {
    const p = preflight(lot({ data_updated_at: iso(-1773), pickup_deadline: iso(-600), cutoff_at: iso(-300) }), [veh(30), veh(1), veh(99, 'offline')], NOW, 60, 5)
    expect(p).toMatchObject({ lotAge: 1773, lotStale: true, pickupPassed: true, cutoffPassed: true, gpsStale: 1, gpsTotal: 2 })
  })
  it('làm mới tuổi lô không biến mốc đã qua thành tương lai', () => {
    const p = preflight(lot({ data_updated_at: iso(0), pickup_deadline: iso(-1) }), [], NOW, 60, 5)
    expect(p.lotStale).toBe(false); expect(p.pickupPassed).toBe(true)
  })
})
