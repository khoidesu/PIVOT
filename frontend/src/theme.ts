// Chế độ giao diện sáng / tối. Lưu ở localStorage (dùng chung giữa trang bao ngoài và các cửa sổ nhúng cùng nguồn gốc);
// chưa chọn → theo cài đặt hệ điều hành. Áp dụng bằng thuộc tính data-theme trên <html> (token màu ở styles.css).
export type Theme = 'light' | 'dark'
const KEY = 'pivot.theme'
const ACCENT_KEY = 'pivot.accent'
export const DEFAULT_ACCENT = '#1a6ff0' // xanh dương của logo (giữa dải #19c6f6 → #1a39f0; chữ trắng trên nền này 4,6:1)
export const ACCENT_PRESETS = [
  '#ff6868', '#35c2cd', '#a98bca', DEFAULT_ACCENT, '#ff7a36',
  '#7352d0', '#e80046', '#f83f8c', '#567d3e', '#8ddbd0',
  '#dff24b', '#a0a0a6', '#06734e', '#800773', '#661f30',
] as const

export const isTheme = (v: unknown): v is Theme => v === 'light' || v === 'dark'

export function systemTheme(): Theme {
  try { return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light' } catch { return 'light' }
}

export function storedTheme(): Theme | null {
  try { const v = localStorage.getItem(KEY); return isTheme(v) ? v : null } catch { return null }
}

/** Chưa chọn → TỐI (hệ thiết kế v3 lấy nền tối làm chính); người dùng đổi bằng nút Sáng/Tối và lựa chọn được nhớ. */
export const currentTheme = (): Theme => storedTheme() ?? 'dark'

export function currentAccent(): string {
  try {
    const value = localStorage.getItem(ACCENT_KEY)
    return value && /^#[\da-f]{6}$/i.test(value) ? value : DEFAULT_ACCENT
  } catch { return DEFAULT_ACCENT }
}

export function applyAccent(value: string, persist = false) {
  if (!/^#[\da-f]{6}$/i.test(value)) return
  const rgb = value.slice(1).match(/.{2}/g)!.map((x) => parseInt(x, 16) / 255)
  const channel = (x: number) => x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
  const ink = 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]) > 0.52 ? '#10110a' : '#ffffff'
  const root = document.documentElement
  root.style.setProperty('--accent-rgb', rgb.map((x) => Math.round(x * 255)).join(', '))
  root.style.setProperty('--primary', value)
  root.style.setProperty('--primary-hover', `color-mix(in srgb, ${value} 82%, white)`)
  root.style.setProperty('--primary-line', `color-mix(in srgb, ${value} 78%, black)`)
  root.style.setProperty('--on-primary', ink)
  root.style.setProperty('--focus', value)
  // --teal/--teal-strong/--teal-weak (chữ nhấn) suy ra trong styles.css theo chế độ sáng/tối để giữ tương phản AA
  root.style.setProperty('--accent', value)
  root.classList.add('has-accent')
  if (persist) { try { localStorage.setItem(ACCENT_KEY, value) } catch { /* bỏ qua */ } }
}

/** Chế độ đang hiển thị thật (index.html đặt sẵn trước khi React chạy: đã lưu → theo lưu, chưa → theo hệ điều hành). */
export const shownTheme = (): Theme => (isTheme(document.documentElement.dataset.theme) ? document.documentElement.dataset.theme : currentTheme())

export function applyTheme(t: Theme, persist = false) {
  document.documentElement.dataset.theme = t
  document.documentElement.style.colorScheme = t // thanh cuộn, ô nhập, chọn ngày theo đúng chế độ
  if (persist) { try { localStorage.setItem(KEY, t) } catch { /* bỏ qua */ } }
}
