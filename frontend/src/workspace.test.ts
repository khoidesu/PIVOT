import { describe, expect, it } from 'vitest'
import { addWin, closeWin, columnsFor, EMPTY, focusWin, MAX_WINS, minimizeWin, moveWin, parse, placement, serialize, setLayout, updateToken, winId, WsLimitError, type WsState } from './workspace'

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

describe('bố cục', () => {
  it('lưới: số cột theo căn bậc hai nhưng không để cửa sổ hẹp hơn 340px', () => {
    expect(columnsFor(1, 'grid', 1200)).toBe(1)
    expect(columnsFor(3, 'grid', 1200)).toBe(2)
    expect(columnsFor(5, 'grid', 1200)).toBe(3)
    expect(columnsFor(5, 'grid', 700)).toBe(2) // 700/340 = 2
    expect(columnsFor(4, 'grid', 400)).toBe(1)
  })
  it('cột: tất cả cạnh nhau nếu đủ rộng, nếu không thì tự xuống hàng', () => {
    expect(columnsFor(4, 'cols', 1400)).toBe(4)
    expect(columnsFor(4, 'cols', 800)).toBe(2)
  })
  it('cửa sổ lẻ cuối hàng giãn hết hàng; thứ tự hiển thị theo `order` (không đổi thứ tự DOM)', () => {
    const p = placement(three(), 1200)
    expect(p.columns).toBe('repeat(2, minmax(0, 1fr))')
    expect(p.items[winId('Khôi', 'node_operator')].gridColumn).toBe('1 / -1')
    expect(p.items[winId('Nguyên', 'shipper')].gridColumn).toBe('auto')
    expect(Object.values(p.items).map((x) => x.order)).toEqual([0, 1, 2])
  })
  it('tập trung: người đang chọn chiếm cột lớn, người khác xếp dọc bên cạnh', () => {
    const s = setLayout(focusWin(three(), winId('Minh', 'carrier')), 'focus')
    const p = placement(s, 1200)
    expect(p.items[winId('Minh', 'carrier')]).toMatchObject({ gridColumn: '1', gridRow: '1 / span 2' })
    expect(p.items[winId('Nguyên', 'shipper')]).toMatchObject({ gridColumn: '2', gridRow: '1' })
    expect(p.items[winId('Khôi', 'node_operator')]).toMatchObject({ gridColumn: '2', gridRow: '2' })
  })
  it('tập trung mà trang quá hẹp thì rơi về lưới; cửa sổ thu nhỏ không có vị trí', () => {
    const s = setLayout(three(), 'focus')
    expect(placement(s, 500).columns).toBe('repeat(1, minmax(0, 1fr))')
    expect(Object.keys(placement(minimizeWin(three(), winId('Minh', 'carrier')), 1200).items)).toHaveLength(2)
  })
})

describe('lưu và khôi phục', () => {
  it('khứ hồi giữ nguyên danh sách, kiểu bố cục và tiêu điểm', () => {
    const s = setLayout(three(), 'cols')
    expect(parse(serialize(s))).toEqual(s)
  })
  it('dữ liệu hỏng hoặc bị sửa tay không làm vỡ trang', () => {
    expect(parse(null)).toEqual(EMPTY)
    expect(parse('{không phải json')).toEqual(EMPTY)
    const r = parse(JSON.stringify({ wins: [{ id: 'a', name: 'A', role: 'hacker', token: 't', open: true }, { id: 'b', name: 'B', role: 'carrier', token: 't', open: true }], layout: 'xyz', focus: 'zzz' }))
    expect(r.wins.map((w) => w.id)).toEqual(['b'])
    expect(r.layout).toBe('grid')
    expect(r.focus).toBe('b')
  })
})
