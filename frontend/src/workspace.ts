// Không gian nhiều cửa sổ: mỗi người đăng nhập = một cửa sổ (khung nhúng của chính ứng dụng) trong cùng một trang.
// Mọi logic ở đây là hàm thuần (không đụng DOM) để test được; màn hình ở screens/Workspace.tsx chỉ vẽ kết quả.
import type { Role } from './api'

export type LayoutMode = 'grid' | 'cols' | 'focus'
export interface Win { id: string; name: string; role: Role; token: string; open: boolean }
export interface WsState { wins: Win[]; focus: string | null; layout: LayoutMode }

export const MAX_WINS = 8
export const MIN_WIN_WIDTH = 340 // px: hẹp hơn thì tự bớt cột (giao diện vẫn dùng được ở ~340px)
export const NARROW_PX = 900 // dưới mức này chỉ hiện một cửa sổ một lúc
export const EMPTY: WsState = { wins: [], focus: null, layout: 'grid' }

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

export const setLayout = (s: WsState, layout: LayoutMode): WsState => ({ ...s, layout })

export interface Placement { columns: string; rows: string; items: Record<string, { gridColumn: string; gridRow: string; order: number }> }

/** Số cột thực tế: theo kiểu bố cục, nhưng không để cửa sổ hẹp hơn MIN_WIN_WIDTH. */
export function columnsFor(n: number, layout: LayoutMode, width: number): number {
  if (n <= 1) return 1
  const fit = Math.max(1, Math.floor(width / MIN_WIN_WIDTH))
  const want = layout === 'cols' ? n : Math.ceil(Math.sqrt(n))
  return Math.max(1, Math.min(want, fit))
}

/** Vị trí từng cửa sổ đang mở trong lưới. Cửa sổ lẻ cuối hàng được giãn hết hàng. */
export function placement(s: WsState, width: number): Placement {
  const open = s.wins.filter((x) => x.open)
  const n = open.length
  const items: Placement['items'] = {}
  const focus = open.find((x) => x.id === s.focus) ?? open[0]
  if (s.layout === 'focus' && n > 1 && width >= MIN_WIN_WIDTH * 2) {
    const others = open.filter((x) => x.id !== focus.id)
    items[focus.id] = { gridColumn: '1', gridRow: `1 / span ${others.length}`, order: 0 }
    others.forEach((x, k) => { items[x.id] = { gridColumn: '2', gridRow: String(k + 1), order: k + 1 } })
    return { columns: 'minmax(0, 2fr) minmax(0, 1fr)', rows: `repeat(${others.length}, minmax(320px, 1fr))`, items }
  }
  const cols = columnsFor(n, s.layout, width)
  const rows = Math.max(1, Math.ceil(n / cols))
  open.forEach((x, k) => {
    const lastOdd = k === n - 1 && cols > 1 && n % cols === 1
    items[x.id] = { gridColumn: lastOdd ? '1 / -1' : 'auto', gridRow: 'auto', order: k }
  })
  return { columns: `repeat(${cols}, minmax(0, 1fr))`, rows: `repeat(${rows}, minmax(420px, 1fr))`, items }
}

// ----- lưu / khôi phục (sessionStorage của trang bao ngoài: tải lại trang không mất danh sách; đóng tab thì mất, như trước) -----
const LAYOUTS: LayoutMode[] = ['grid', 'cols', 'focus']
const ROLE_SET = ['shipper', 'carrier', 'node_operator', 'dispatcher']

export function serialize(s: WsState): string { return JSON.stringify(s) }

export function parse(raw: string | null): WsState {
  if (!raw) return EMPTY
  try {
    const d = JSON.parse(raw) as Partial<WsState>
    const wins = (Array.isArray(d.wins) ? d.wins : []).filter((w): w is Win =>
      !!w && typeof w.id === 'string' && typeof w.name === 'string' && typeof w.token === 'string' && ROLE_SET.includes(w.role as string) && typeof w.open === 'boolean').slice(0, MAX_WINS)
    const layout = LAYOUTS.includes(d.layout as LayoutMode) ? (d.layout as LayoutMode) : 'grid'
    const focus = wins.some((w) => w.id === d.focus) ? (d.focus as string) : firstOpen(wins)
    return { wins, focus, layout }
  } catch { return EMPTY }
}

/** Bốn người cố định của nhóm: bấm một lần để vào (không cần gõ). */
// Phước là chủ hàng thứ hai CÙNG tổ chức với Nguyên: dùng để thử "hai người cùng bên" (vd cùng giữ một tài nguyên → chỉ một thành công).
export const TEAM: { name: string; role: Role }[] = [
  { name: 'Nguyên', role: 'shipper' }, { name: 'Phước', role: 'shipper' }, { name: 'Minh', role: 'carrier' },
  { name: 'Khôi', role: 'node_operator' }, { name: 'Phú', role: 'dispatcher' },
]
export const CHAIN = [TEAM[0], TEAM[2], TEAM[3]] // chuỗi ba bên: chủ hàng → vận tải → ICD
