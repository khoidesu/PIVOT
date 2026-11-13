import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { dictionaries, reasonText, translate } from './i18n'
import { allowedRoute, defaultRoute, navFor } from './nav'

const REASON_CODES = ['CAPACITY_EXCEEDED', 'CARGO_INCOMPATIBLE', 'DATA_STALE', 'PICKUP_WINDOW_MISSED', 'CUTOFF_RISK',
  'VEHICLE_UNAVAILABLE', 'SLOT_FULL', 'SLOT_WINDOW_MISSED', 'SLOT_LOCATION_MISMATCH', 'SLOT_AFTER_CUTOFF', 'MISSING_FIELD', 'SHIPMENT_NOT_OPEN', 'ID_UNRESOLVED']

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
  it('BUG-01: SLOT_WINDOW_MISSED đầy đủ / bị che / thiếu trường không bao giờ lộ placeholder', () => {
    const iso = '2026-11-12T09:00:00+07:00'
    for (const lang of ['vi', 'en'] as const) {
      const t = (k: string, p?: Record<string, string | number>) => translate(lang, k, p)
      const r = (detail: Record<string, unknown>) => reasonText({ gate: 'slot', status: 'FAIL', reason_code: 'SLOT_WINDOW_MISSED', detail }, t, () => '09:00')
      const full = r({ eta_icd: iso, slot_end_at: iso })                       // nhà vận tải chủ xe
      const redacted = r({ slot_end_at: iso, redacted: true })                // chủ hàng: chỉ giờ của slot, không có ETA xe bên khác
      const missing = r({ redacted: true })                                   // field thiếu ngoài dự kiến
      for (const txt of [full, redacted, missing]) expect(txt, `${lang}: ${txt}`).not.toMatch(/\{\w+\}/)
      expect(redacted).toContain('09:00')
      expect(missing.length).toBeGreaterThan(5)
    }
  })
  it('mọi template lý do: thiếu hết dữ kiện vẫn ra câu đọc được (phòng vệ redaction)', () => {
    const t = (k: string, p?: Record<string, string | number>) => translate('vi', k, p)
    const codes = Object.keys(dictionaries.vi).filter((k) => /^reason\.[A-Z_]+$/.test(k)).map((k) => k.slice(7))
    for (const code of codes) {
      for (const detail of [{}, { redacted: true }]) expect(reasonText({ gate: 'x', status: 'FAIL', reason_code: code, detail }, t, (x) => x), code).not.toMatch(/\{\w+\}/)
    }
  })
  it('BUG-03: chủ hàng thấy vượt thể tích hay trọng lượng, không thấy capacity xe', () => {
    for (const lang of ['vi', 'en'] as const) {
      const t = (k: string, p?: Record<string, string | number>) => translate(lang, k, p)
      const vol = reasonText({ gate: 'capacity', status: 'FAIL', reason_code: 'CAPACITY_EXCEEDED', detail: { weight_kg: 1000, volume_m3: 30, over: ['volume'], redacted: true } }, t, (x) => x)
      expect(vol).toContain('30 m³'); expect(vol).not.toContain('1000'); expect(vol).toMatch(/thể tích|volume/)
      const kg = reasonText({ gate: 'capacity', status: 'FAIL', reason_code: 'CAPACITY_EXCEEDED', detail: { weight_kg: 30000, volume_m3: 30, over: ['weight'], redacted: true } }, t, (x) => x)
      expect(kg).toContain('30000'); expect(kg).toMatch(/trọng tải|weight/)
    }
  })
  it('mọi mã ghi chú nhập liệu và mã lỗi mới đều có bản dịch', () => {
    for (const lang of ['vi', 'en'] as const) {
      for (const n of ['MISSING', 'AMBIGUOUS', 'QUOTE_NOT_FOUND_IN_SOURCE', 'INVALID_VALUE', 'RELATIVE_DATE_ASSUMED', 'TIME_ORDER_INVALID']) expect(dictionaries[lang][`in.note.${n}`], `${lang}:${n}`).toBeTruthy()
      for (const c of ['INVALID_NAME', 'INVALID_ROLE', 'REGISTRATION_LIMIT', 'SHIPMENT_LOCKED', 'NOT_INDEPENDENT', 'NO_INDEPENDENT_VERIFIER', 'NOT_MEASURED', 'VERSION_CONFLICT', 'CARGO_ON_BOARD']) expect(dictionaries[lang][`err.${c}`], `${lang}:${c}`).toBeTruthy()
    }
  })
  it('màn hình đăng nhập có đủ chữ cho 4 vai trò ở cả hai ngôn ngữ', () => {
    for (const lang of ['vi', 'en'] as const)
      for (const r of ['shipper', 'carrier', 'node_operator', 'dispatcher']) {
        expect(dictionaries[lang][`role.${r}`], `${lang}:role.${r}`).toBeTruthy()
        expect(dictionaries[lang][`rd.${r}`], `${lang}:rd.${r}`).toBeTruthy()
      }
  })
  it('mã lỗi không biết vẫn hiển thị được (không vỡ UI)', () => {
    const t = (k: string, p?: Record<string, string | number>) => translate('vi', k, p)
    expect(reasonText({ gate: 'x', status: 'FAIL', reason_code: 'NEW_CODE', detail: {} }, t, (s) => s)).toContain('x')
  })
})

const SRC = join(__dirname)
const walk = (d: string): string[] => readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(d, e.name)) : [join(d, e.name)]))
const wordsOf = (lang: 'vi' | 'en') => Object.values(dictionaries[lang]).reduce((n, v) => n + v.split(/\s+/).filter(Boolean).length, 0)

describe('giao diện gọn chữ', () => {
  it('ngân sách chữ tiếng Việt không phình lại (2.750 từ sau khi giải thích mô hình nhà xe; nới lên 3.000 để có hướng dẫn prototype 6 bước, tên thao tác và giải nghĩa ETA/ICD)', () => {
    expect(wordsOf('vi')).toBeLessThanOrEqual(3000)
  })
  it('mọi khoá i18n đều được mã nguồn dùng (không để chuỗi chết)', () => {
    const code = walk(SRC).filter((f) => /\.(tsx?)$/.test(f) && !/i18n(\.test)?\.ts$/.test(f)).map((f) => readFileSync(f, 'utf8')).join('\n')
    const dynamic = ['status.', 'ps.', 'cargo.', 'role.', 'rd.', 'party.', 'gate.', 'reason.', 'tl.code.', 'tl.q.', 'tl.resolve.', 'tl.exc.', 'in.note.', 'in.f.', 'err.',
      'demo.s.', 'rec.comp.', 'rec.s.', 'bf.status.', 'bf.sub.', 'nav.', 'fleet.tab.', 'cf.ok.', 'tk.ms.', 'tk.mode.', 'ex.sev.', 'ex.cat.', 'ex.step.', 'ex.owner.', 'ex.kind.', 'dk.status.', 'eta.status.', 'eta.reason.', 'eta.band.', 'veh.state.', 'sbx.vs.', 'ws.layout.', 'theme.', 'in.llm.', 'in.img.', 'land.g']
    const dead = Object.keys(dictionaries.vi).filter((k) => !dynamic.some((p) => k.startsWith(p)) && !code.includes(`'${k}'`) && !code.includes(`\`${k}\``))
    expect(dead).toEqual([])
  })
  it('thanh đầu có tên LOGECTION', () => {
    expect(readFileSync(join(SRC, 'components', 'TopBar.tsx'), 'utf8')).toContain('LOGECTION')
    expect(readFileSync(join(SRC, '..', 'index.html'), 'utf8')).toContain('<title>LOGECTION</title>')
  })
})

describe('menu theo vai trò', () => {
  it('mỗi vai trò chỉ thấy mục liên quan', () => {
    expect(navFor('shipper')).toEqual(['request', 'fleet', 'recommend', 'confirm', 'tracking', 'exceptions', 'timeline', 'benefits'])
    expect(navFor('carrier')).toEqual(['fleet', 'recommend', 'confirm', 'docks', 'tracking', 'exceptions', 'timeline', 'benefits'])
    expect(navFor('node_operator')).toEqual(['fleet', 'confirm', 'docks', 'tracking', 'exceptions', 'timeline'])
    expect(navFor('dispatcher')).toEqual(['fleet', 'recommend', 'confirm', 'docks', 'tracking', 'exceptions', 'timeline', 'benefits'])
    expect(navFor(undefined)).toEqual([])
  })
  it('ICD không vào được Ghép/Lợi ích; Demo chỉ dành cho điều phối viên và không nằm ở menu chính', () => {
    expect(allowedRoute('node_operator', 'recommend')).toBe(false)
    expect(allowedRoute('node_operator', 'benefits')).toBe(false)
    for (const r of ['shipper', 'carrier', 'node_operator']) expect(allowedRoute(r, 'demo')).toBe(false)
    expect(allowedRoute('dispatcher', 'demo')).toBe(true)
    expect(navFor('dispatcher')).not.toContain('demo')
  })
  it('chỉ chủ hàng vào được "Yêu cầu": nhà vận tải (kể cả deep link) và điều phối viên không tạo lô (BUG-02)', () => {
    expect(allowedRoute('shipper', 'request')).toBe(true)
    expect(allowedRoute('carrier', 'request')).toBe(false)
    expect(allowedRoute('node_operator', 'request')).toBe(false)
    expect(allowedRoute('dispatcher', 'request')).toBe(false)
  })
  it('mục mặc định theo vai trò', () => {
    expect(defaultRoute('shipper')).toBe('request')
    for (const r of ['carrier', 'node_operator', 'dispatcher']) expect(defaultRoute(r)).toBe('fleet')
  })
})
