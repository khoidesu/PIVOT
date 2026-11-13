// Không gian nhiều cửa sổ: mỗi người đăng nhập = một cửa sổ (khung nhúng của chính ứng dụng) trong cùng một trang.
// Mọi logic ở đây là hàm thuần (không đụng DOM) để test được; màn hình ở screens/Workspace.tsx chỉ vẽ kết quả.
import type { Role } from './api'

/** Tỉ lệ khung do người dùng kéo: chiều cao từng hàng và chiều rộng từng cột trong mỗi hàng (mỗi mảng cộng lại = 1). */
export interface Sizes { rows: number[]; cols: number[][] }
export interface Win { id: string; name: string; role: Role; token: string; open: boolean }
export interface WsState { wins: Win[]; focus: string | null; sizes?: Sizes }

export const MAX_WINS = 8
export const MIN_WIN_WIDTH = 340 // px: hẹp hơn thì tự bớt cột (giao diện vẫn dùng được ở ~340px)
export const NARROW_PX = 900 // dưới mức này chỉ hiện một cửa sổ một lúc
export const EMPTY: WsState = { wins: [], focus: null }
export const MIN_FRAC = 0.12 // một khung không bị kéo nhỏ hơn 12% hàng/cột của nó

const fold = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/gi, 'd').toLowerCase().replace(/\s+/g, ' ').trim()
/** Cùng tên (không phân biệt hoa/dấu) + cùng vai trò = cùng một người = cùng một cửa sổ. */
export const winId = (name: string, role: Role) => `${role}:${fold(name)}`

export class WsLimitError extends Error { constructor() { super('WS_LIMIT') } }

/** Mở (hoặc đưa lên) cửa sổ của một người; người mới vượt trần → WsLimitError. Token mới ghi đè token cũ. */
export function addWin(s: WsState, w: Omit<Win, 'open'>): WsState {
  const i = s.wins.findIndex((x) => x.id === w.id)
  if (i >= 0) return { ...s, focus: w.id, wins: s.wins.map((x, k) => (k === i ? { ...x, token: w.token, name: w.name, open: true } : x)) }
  if (s.wins.length >= MAX_WINS) throw new WsLimitError()
  return { ...s, focus: w.id, wins: [...s.wins, { ...w, open: true }] }
}

const firstOpen = (wins: Win[], except?: string) => wins.find((x) => x.open && x.id !== except)?.id ?? null

export function focusWin(s: WsState, id: string): WsState {
  const w = s.wins.find((x) => x.id === id)
  return w ? { ...s, focus: id, wins: s.wins.map((x) => (x.id === id ? { ...x, open: true } : x)) } : s
}

/** Thu nhỏ: cửa sổ ẩn nhưng người đó vẫn đăng nhập và vẫn chạy nền (còn nhận việc chờ). */
export function minimizeWin(s: WsState, id: string): WsState {
  const wins = s.wins.map((x) => (x.id === id ? { ...x, open: false } : x))
  return { ...s, wins, focus: s.focus === id ? firstOpen(wins) : s.focus }
}

export function closeWin(s: WsState, id: string): WsState {
  const wins = s.wins.filter((x) => x.id !== id)
  return { ...s, wins, focus: s.focus === id ? firstOpen(wins) : s.focus }
}

export function updateToken(s: WsState, id: string, token: string): WsState {
  return { ...s, wins: s.wins.map((x) => (x.id === id ? { ...x, token } : x)) }
}

/** Đưa cửa sổ `from` tới vị trí của cửa sổ `to` (thứ tự hiển thị). */
export function moveWin(s: WsState, from: string, to: string): WsState {
  const a = s.wins.findIndex((x) => x.id === from)
  const b = s.wins.findIndex((x) => x.id === to)
  if (a < 0 || b < 0 || a === b) return s
  const wins = s.wins.slice()
  const [it] = wins.splice(a, 1)
  wins.splice(b, 0, it)
  return { ...s, wins }
}

/** Chèn cửa sổ kéo vào trước/sau cửa sổ đích; center đổi chỗ như thao tác cũ. */
export function insertWin(s: WsState, from: string, to: string, side: 'left' | 'right' | 'top' | 'bottom' | 'center'): WsState {
  const a = s.wins.findIndex((x) => x.id === from), b = s.wins.findIndex((x) => x.id === to)
  if (a < 0 || b < 0 || a === b) return s
  if (side === 'center') return moveWin(s, from, to)
  const wins = s.wins.slice(), [item] = wins.splice(a, 1)
  const target = wins.findIndex((x) => x.id === to)
  wins.splice(target + (side === 'right' || side === 'bottom' ? 1 : 0), 0, item)
  return { ...s, wins }
}

/** Số cột mỗi hàng: gần vuông (√n), nhưng không để cửa sổ hẹp hơn MIN_WIN_WIDTH. */
export function columnsFor(n: number, width: number): number {
  if (n <= 1) return 1
  const capacity = Math.max(1, Math.floor(width / MIN_WIN_WIDTH))
  // Ba khung giữ cùng một hàng khi đủ rộng; hữu ích khi thả cửa sổ mới giữa hai tài khoản.
  if (n === 3 && capacity >= 3) return 3
  return Math.max(1, Math.min(Math.ceil(Math.sqrt(n)), capacity))
}

/** Hình dạng bố cục: số cửa sổ ở từng hàng (hàng cuối có thể ít hơn → các cửa sổ đó tự rộng ra). */
export function shapeOf(n: number, width: number): number[] {
  if (n <= 0) return []
  const cols = columnsFor(n, width)
  const out: number[] = []
  for (let left = n; left > 0; left -= cols) out.push(Math.min(cols, left))
  return out
}

const even = (k: number) => Array.from({ length: k }, () => 1 / k)
const okFracs = (a: unknown, k: number): a is number[] =>
  Array.isArray(a) && a.length === k && a.every((x) => typeof x === 'number' && x >= MIN_FRAC / 2 && x <= 1) && Math.abs(a.reduce((p, c) => p + c, 0) - 1) < 0.02

/** Tỉ lệ đang áp dụng: của người dùng nếu còn khớp hình dạng hiện tại, không thì chia đều (mở/đóng cửa sổ làm đổi hình dạng → về chia đều). */
export function sizesFor(sizes: Sizes | undefined, shape: number[]): Sizes {
  const fits = !!sizes && okFracs(sizes.rows, shape.length) && Array.isArray(sizes.cols) && sizes.cols.length === shape.length && shape.every((k, r) => okFracs(sizes.cols[r], k))
  return fits ? sizes! : { rows: even(shape.length), cols: shape.map(even) }
}

export interface Rect { left: number; top: number; width: number; height: number } // phần trăm của vùng làm việc
export interface Splitter { kind: 'col' | 'row'; row: number; index: number; left: number; top: number; width: number; height: number; value: number }
export interface Placement { shape: number[]; sizes: Sizes; items: Record<string, Rect>; splitters: Splitter[] }

/** Vị trí từng cửa sổ đang mở + các thanh kéo giữa chúng. Vị trí là tuyệt đối (%), nên đổi chỗ/kéo giãn không làm đổi thứ tự DOM. */
export function placement(s: WsState, width: number): Placement {
  const open = s.wins.filter((x) => x.open)
  const shape = shapeOf(open.length, width)
  const sizes = sizesFor(s.sizes, shape)
  const items: Placement['items'] = {}
  const splitters: Splitter[] = []
  let k = 0, top = 0
  shape.forEach((n, r) => {
    const h = sizes.rows[r] * 100
    let left = 0
    for (let c = 0; c < n; c++) {
      const w = sizes.cols[r][c] * 100
      items[open[k++].id] = { left, top, width: w, height: h }
      left += w
      if (c < n - 1) splitters.push({ kind: 'col', row: r, index: c, left, top, width: 0, height: h, value: Math.round(sizes.cols[r][c] * 100) })
    }
    top += h
    if (r < shape.length - 1) splitters.push({ kind: 'row', row: r, index: r, left: 0, top, width: 100, height: 0, value: Math.round(sizes.rows[r] * 100) })
  })
  return { shape, sizes, items, splitters }
}

/** Kéo một thanh chia đi `delta` (phần của hàng/cột, −1..1): khung trước nó to ra, khung sau nó nhỏ lại; cả hai không dưới MIN_FRAC. */
export function dragSplit(s: WsState, width: number, sp: Pick<Splitter, 'kind' | 'row' | 'index'>, delta: number): WsState {
  const shape = shapeOf(s.wins.filter((x) => x.open).length, width)
  const cur = sizesFor(s.sizes, shape)
  const arr = (sp.kind === 'row' ? cur.rows : cur.cols[sp.row])?.slice()
  if (!arr || sp.index < 0 || sp.index >= arr.length - 1 || !Number.isFinite(delta)) return s
  const pair = arr[sp.index] + arr[sp.index + 1]
  const a = Math.min(pair - MIN_FRAC, Math.max(MIN_FRAC, arr[sp.index] + delta))
  if (pair < MIN_FRAC * 2) return s
  arr[sp.index] = a; arr[sp.index + 1] = pair - a
  const sizes: Sizes = sp.kind === 'row' ? { rows: arr, cols: cur.cols } : { rows: cur.rows, cols: cur.cols.map((c, r) => (r === sp.row ? arr : c)) }
  return { ...s, sizes }
}

/** Trả mọi khung về chia đều. */
export const resetSizes = (s: WsState): WsState => { const { sizes: _drop, ...rest } = s; return rest }

// ----- lưu / khôi phục (sessionStorage của trang bao ngoài: tải lại trang không mất danh sách; đóng tab thì mất, như trước) -----
const ROLE_SET = ['shipper', 'carrier', 'node_operator', 'dispatcher']

export function serialize(s: WsState): string { return JSON.stringify(s) }

export function parse(raw: string | null): WsState {
  if (!raw) return EMPTY
  try {
    const d = JSON.parse(raw) as Partial<WsState>
    const wins = (Array.isArray(d.wins) ? d.wins : []).filter((w): w is Win =>
      !!w && typeof w.id === 'string' && typeof w.name === 'string' && typeof w.token === 'string' && ROLE_SET.includes(w.role as string) && typeof w.open === 'boolean').slice(0, MAX_WINS)
    const z = d.sizes as Sizes | undefined
    const sizes = z && Array.isArray(z.rows) && Array.isArray(z.cols) && z.rows.every((x) => typeof x === 'number') && z.cols.every((c) => Array.isArray(c) && c.every((x) => typeof x === 'number')) ? { rows: z.rows, cols: z.cols } : undefined
    const focus = wins.some((w) => w.id === d.focus) ? (d.focus as string) : firstOpen(wins)
    return sizes ? { wins, focus, sizes } : { wins, focus }
  } catch { return EMPTY }
}

/** Bốn người cố định của nhóm: bấm một lần để vào (không cần gõ). */
// Phước là chủ hàng thứ hai CÙNG tổ chức với Nguyên: dùng để thử "hai người cùng bên" (vd cùng giữ một tài nguyên → chỉ một thành công).
export const TEAM: { name: string; role: Role }[] = [
  { name: 'Nguyên', role: 'shipper' }, { name: 'Phước', role: 'shipper' }, { name: 'Minh', role: 'carrier' },
  { name: 'Khôi', role: 'node_operator' }, { name: 'Phú', role: 'dispatcher' },
]
export const CHAIN = [TEAM[0], TEAM[2], TEAM[3]] // chuỗi ba bên: chủ hàng → vận tải → ICD
