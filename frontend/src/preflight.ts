// Kiểm tra trước khi ghép (BUG-04): cho thấy đầu vào đã cũ/quá hạn TRƯỚC khi chạy, và tách "dữ liệu cũ" (làm mới được)
// khỏi "mốc giờ đã qua" (làm mới không giúp — phải sửa giờ của lô). Chỉ hiển thị; hard gate ở backend vẫn quyết định.
import type { Shipment, Vehicle } from './api'

export interface Preflight {
  lotAge: number; lotStale: boolean
  pickupPassed: boolean; cutoffPassed: boolean
  gpsStale: number; gpsTotal: number // chỉ xe người xem thấy được (chủ hàng không thấy đội xe bên khác → 0/0)
}

export function preflight(lot: Shipment, vehicles: Vehicle[], now: number, lotLimitMin: number, gpsLimitMin: number): Preflight {
  const age = (iso: string | null) => (iso ? (now - new Date(iso).getTime()) / 60000 : Infinity)
  const lotAge = Math.max(0, Math.round(age(lot.data_updated_at)))
  const avail = vehicles.filter((v) => v.status === 'available')
  return {
    lotAge, lotStale: lotAge > lotLimitMin,
    pickupPassed: !!lot.pickup_deadline && new Date(lot.pickup_deadline).getTime() <= now,
    cutoffPassed: !!lot.cutoff_at && new Date(lot.cutoff_at).getTime() <= now,
    gpsStale: avail.filter((v) => age(v.position_updated_at) > gpsLimitMin).length, gpsTotal: avail.length,
  }
}
