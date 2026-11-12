// Chế độ giao diện sáng / tối. Lưu ở localStorage (dùng chung giữa trang bao ngoài và các cửa sổ nhúng cùng nguồn gốc);
// chưa chọn → theo cài đặt hệ điều hành. Áp dụng bằng thuộc tính data-theme trên <html> (token màu ở styles.css).
export type Theme = 'light' | 'dark'
const KEY = 'pivot.theme'

export const isTheme = (v: unknown): v is Theme => v === 'light' || v === 'dark'

export function systemTheme(): Theme {
  try { return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light' } catch { return 'light' }
}

export function storedTheme(): Theme | null {
  try { const v = localStorage.getItem(KEY); return isTheme(v) ? v : null } catch { return null }
}

export const currentTheme = (): Theme => storedTheme() ?? systemTheme()

export function applyTheme(t: Theme, persist = false) {
  document.documentElement.dataset.theme = t
  document.documentElement.style.colorScheme = t // thanh cuộn, ô nhập, chọn ngày theo đúng chế độ
  if (persist) { try { localStorage.setItem(KEY, t) } catch { /* bỏ qua */ } }
}
