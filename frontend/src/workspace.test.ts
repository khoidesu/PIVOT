import { describe, expect, it } from 'vitest'
import { addWin, closeWin, columnsFor, EMPTY, focusWin, MAX_WINS, minimizeWin, moveWin, parse, placement, resetSizes, serialize, shapeOf, dragSplit, updateToken, winId, WsLimitError, type WsState } from './workspace'

const mk = (name: string, role: 'shipper' | 'carrier' | 'node_operator' | 'dispatcher' = 'shipper') => ({ id: winId(name, role), name, role, token: `k-${name}` })
const three = (): WsState => addWin(addWin(addWin(EMPTY, mk('Nguyên')), mk('Minh', 'carrier')), mk('Khôi', 'node_operator'))
const ids = (s: WsState) => s.wins.map((w) => w.name)

describe('cửa sổ', () => {
  it('cùng tên (không phân biệt hoa/dấu) + cùng vai trò là một cửa sổ; khác vai trò là người khác', () => {
    expect(winId('Nguyên', 'shipper')).toBe(winId('  nguyen ', 'shipper'))
    expect(winId('Hòa', 'carrier')).toBe(winId('hoa', 'carrier'))
    expect(winId('Minh', 'shipper')).not.toBe(winId('Minh', 'carrier'))
  })
  it('thêm người: mở và đưa lên; thêm lại người đã có thì mở lại, không nhân đôi', () => {
    let s = three()
    expect(s.wins).toHaveLength(3)
    expect(s.focus).toBe(winId('Khôi', 'node_operator'))
    s = minimizeWin(s, winId('Minh', 'carrier'))
    s = addWin(s, { ...mk('Minh', 'carrier'), token: 'moi' })
    expect(s.wins).toHaveLength(3)
    expect(s.wins.find((w) => w.name === 'Minh')).toMatchObject({ open: true, token: 'moi' })
    expect(s.focus).toBe(winId('Minh', 'carrier'))
  })
  it(`có trần ${MAX_WINS} người; người đã có vẫn thêm lại được`, () => {
    let s = EMPTY
    for (let i = 0; i < MAX_WINS; i++) s = addWin(s, mk(`P${i}`))
    expect(() => addWin(s, mk('Dư'))).toThrow(WsLimitError)
    expect(addWin(s, mk('P0')).wins).toHaveLength(MAX_WINS)
  })
  it('thu nhỏ giữ người đó (chạy nền) và chuyển tiêu điểm sang cửa sổ mở kế tiếp', () => {
    const s = minimizeWin(three(), winId('Khôi', 'node_operator'))
    expect(s.wins).toHaveLength(3)
    expect(s.wins.find((w) => w.name === 'Khôi')?.open).toBe(false)
    expect(s.focus).toBe(winId('Nguyên', 'shipper'))
    expect(focusWin(s, winId('Khôi', 'node_operator')).wins.find((w) => w.name === 'Khôi')?.open).toBe(true)
  })
  it('đóng bỏ hẳn người đó; đóng hết thì không còn tiêu điểm', () => {
    let s = closeWin(three(), winId('Nguyên', 'shipper'))
    expect(ids(s)).toEqual(['Minh', 'Khôi'])
    s = closeWin(closeWin(s, winId('Minh', 'carrier')), winId('Khôi', 'node_operator'))
    expect(s.wins).toEqual([])
    expect(s.focus).toBeNull()
  })
  it('đổi chỗ bằng kéo thả; id lạ không làm gì', () => {
    const s = moveWin(three(), winId('Khôi', 'node_operator'), winId('Nguyên', 'shipper'))
    expect(ids(s)).toEqual(['Khôi', 'Nguyên', 'Minh'])
    const same = three()
    expect(moveWin(same, 'x', winId('Minh', 'carrier'))).toBe(same)
  })
  it('đổi token khi đăng nhập lại sau khi phiên hết hạn', () => {
    expect(updateToken(three(), winId('Minh', 'carrier'), 'new').wins[1].token).toBe('new')
  })
})

describe('bố cục kéo giãn (khung chia như trình soạn mã)', () => {
  it('số cột gần vuông, không để cửa sổ hẹp hơn mức tối thiểu', () => {
    expect(columnsFor(1, 1200)).toBe(1)
    expect(columnsFor(4, 1200)).toBe(2)
    expect(columnsFor(5, 700)).toBe(2) // 700/340 = 2
    expect(columnsFor(4, 400)).toBe(1)
    expect(shapeOf(3, 1200)).toEqual([2, 1])
    expect(shapeOf(5, 1400)).toEqual([3, 2])
    expect(shapeOf(0, 1200)).toEqual([])
  })
  it('mặc định chia đều; cửa sổ lẻ cuối hàng rộng hết hàng; cửa sổ thu nhỏ không có vị trí', () => {
    const p = placement(three(), 1200)
    expect(p.items[winId('Nguyên', 'shipper')]).toEqual({ left: 0, top: 0, width: 50, height: 50 })
    expect(p.items[winId('Minh', 'carrier')]).toEqual({ left: 50, top: 0, width: 50, height: 50 })
    expect(p.items[winId('Khôi', 'node_operator')]).toEqual({ left: 0, top: 50, width: 100, height: 50 })
    expect(p.splitters.map((x) => x.kind)).toEqual(['col', 'row'])
    expect(Object.keys(placement(minimizeWin(three(), winId('Minh', 'carrier')), 1200).items)).toHaveLength(2)
  })
  it('kéo thanh chia: khung trước to ra, khung sau nhỏ lại, tổng không đổi', () => {
    const s = dragSplit(three(), 1200, { kind: 'col', row: 0, index: 0 }, 0.2)
    const p = placement(s, 1200)
    expect(p.items[winId('Nguyên', 'shipper')].width).toBeCloseTo(70)
    expect(p.items[winId('Minh', 'carrier')]).toMatchObject({ left: 70 })
    expect(p.items[winId('Minh', 'carrier')].width).toBeCloseTo(30)
    const r = placement(dragSplit(s, 1200, { kind: 'row', row: 0, index: 0 }, -0.1), 1200)
    expect(r.items[winId('Khôi', 'node_operator')].height).toBeCloseTo(60)
    expect(r.items[winId('Nguyên', 'shipper')].width).toBeCloseTo(70) // kéo hàng không làm mất tỉ lệ cột
  })
  it('không kéo nhỏ hơn mức tối thiểu; thanh không tồn tại thì bỏ qua', () => {
    const p = placement(dragSplit(three(), 1200, { kind: 'col', row: 0, index: 0 }, 0.9), 1200)
    expect(p.items[winId('Minh', 'carrier')].width).toBeCloseTo(12)
    expect(dragSplit(three(), 1200, { kind: 'col', row: 1, index: 0 }, 0.1)).toEqual(three())
    expect(dragSplit(three(), 1200, { kind: 'row', row: 0, index: 5 }, 0.1)).toEqual(three())
  })
  it('mở/đóng cửa sổ làm đổi hình dạng → về chia đều; đặt lại xoá tỉ lệ', () => {
    const s = dragSplit(three(), 1200, { kind: 'col', row: 0, index: 0 }, 0.2)
    const closed = closeWin(s, winId('Khôi', 'node_operator'))
    expect(placement(closed, 1200).items[winId('Nguyên', 'shipper')]).toEqual({ left: 0, top: 0, width: 50, height: 100 })
    expect(resetSizes(s).sizes).toBeUndefined()
    expect(placement(s, 500).shape).toEqual([1, 1, 1]) // trang hẹp: mỗi hàng một cửa sổ, tỉ lệ cũ không còn khớp
  })
})

describe('lưu và khôi phục', () => {
  it('khứ hồi giữ nguyên danh sách, tỉ lệ khung và tiêu điểm', () => {
    const s = dragSplit(three(), 1200, { kind: 'col', row: 0, index: 0 }, 0.2)
    expect(parse(serialize(s))).toEqual(s)
  })
  it('dữ liệu hỏng hoặc bị sửa tay không làm vỡ trang', () => {
    expect(parse(null)).toEqual(EMPTY)
    expect(parse('{không phải json')).toEqual(EMPTY)
    const r = parse(JSON.stringify({ wins: [{ id: 'a', name: 'A', role: 'hacker', token: 't', open: true }, { id: 'b', name: 'B', role: 'carrier', token: 't', open: true }], sizes: 'xyz', focus: 'zzz' }))
    expect(r.wins.map((w) => w.id)).toEqual(['b'])
    expect(r.sizes).toBeUndefined()
    expect(r.focus).toBe('b')
  })
})
