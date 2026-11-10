import { describe, expect, it } from 'vitest'
import { dictionaries, reasonText, translate } from './i18n'

const REASON_CODES = ['CAPACITY_EXCEEDED', 'CARGO_INCOMPATIBLE', 'DATA_STALE', 'PICKUP_WINDOW_MISSED', 'CUTOFF_RISK',
  'VEHICLE_UNAVAILABLE', 'SLOT_FULL', 'SLOT_WINDOW_MISSED', 'SLOT_LOCATION_MISMATCH', 'MISSING_FIELD', 'SHIPMENT_NOT_OPEN', 'ID_UNRESOLVED']

describe('i18n', () => {
  it('vi và en có cùng bộ khoá', () => {
    expect(Object.keys(dictionaries.en).sort()).toEqual(Object.keys(dictionaries.vi).sort())
  })
  it('mọi reason_code của backend đều có template ở cả hai ngôn ngữ', () => {
    for (const lang of ['vi', 'en'] as const)
      for (const c of REASON_CODES) expect(dictionaries[lang][`reason.${c}`], `${lang}:${c}`).toBeTruthy()
  })
  it('reasonText điền số liệu thật của gate vào template, không để placeholder', () => {
    const t = (k: string, p?: Record<string, string | number>) => translate('vi', k, p)
    const txt = reasonText({ gate: 'capacity', status: 'FAIL', reason_code: 'CAPACITY_EXCEEDED',
      detail: { weight_kg: 20000, capacity_kg: 8000, volume_m3: 50, capacity_m3: 25 } }, t, (s) => s)
    expect(txt).toContain('20000')
    expect(txt).toContain('8000')
    expect(txt).not.toMatch(/\{\w+\}/)
  })
  it('dùng template riêng cho DATA_STALE của lô và xe đã được giữ', () => {
    const t = (k: string, p?: Record<string, string | number>) => translate('en', k, p)
    const shipment = reasonText({ gate: 'shipment_fresh', status: 'FAIL', reason_code: 'DATA_STALE', detail: { subject: 'shipment', age_minutes: 90, limit_minutes: 60 } }, t, (s) => s)
    expect(shipment).toMatch(/Shipment data/)
    const reserved = reasonText({ gate: 'vehicle_available', status: 'FAIL', reason_code: 'VEHICLE_UNAVAILABLE', detail: { reserved: true } }, t, (s) => s)
    expect(reserved).toMatch(/held\/committed/)
  })
  it('chi tiết đội xe đã bị che → dùng template ngắn, không còn placeholder', () => {
    for (const lang of ['vi', 'en'] as const) {
      const t = (k: string, p?: Record<string, string | number>) => translate(lang, k, p)
      const txt = reasonText({ gate: 'capacity', status: 'FAIL', reason_code: 'CAPACITY_EXCEEDED', detail: { weight_kg: 20000, volume_m3: 50, redacted: true } }, t, (x) => x)
      expect(txt).toContain('20000')
      expect(txt).not.toMatch(/\{\w+\}/)
      expect(txt).not.toMatch(/capacity_kg/)
    }
  })
  it('mọi mã ghi chú nhập liệu và mã lỗi mới đều có bản dịch', () => {
    for (const lang of ['vi', 'en'] as const) {
      for (const n of ['MISSING', 'AMBIGUOUS', 'QUOTE_NOT_FOUND_IN_SOURCE', 'INVALID_VALUE', 'RELATIVE_DATE_ASSUMED', 'TIME_ORDER_INVALID']) expect(dictionaries[lang][`in.note.${n}`], `${lang}:${n}`).toBeTruthy()
      for (const c of ['SHIPMENT_LOCKED', 'NOT_INDEPENDENT', 'NO_INDEPENDENT_VERIFIER', 'NOT_MEASURED', 'VERSION_CONFLICT']) expect(dictionaries[lang][`err.${c}`], `${lang}:${c}`).toBeTruthy()
    }
  })
  it('mã lỗi không biết vẫn hiển thị được (không vỡ UI)', () => {
    const t = (k: string, p?: Record<string, string | number>) => translate('vi', k, p)
    expect(reasonText({ gate: 'x', status: 'FAIL', reason_code: 'NEW_CODE', detail: {} }, t, (s) => s)).toContain('x')
  })
})
