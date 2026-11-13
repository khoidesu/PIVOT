import type { ApiError } from './api'

/** Nhịp tự thử lại khi lỗi mà màn không polling (QA-07): mất kết nối rồi API sống lại thì tự hồi, không cần chuyển màn. */
export const RETRY_MS = 4000

/** Lỗi do mất kết nối / máy chủ không trả lời (khác lỗi nghiệp vụ 4xx). */
export const isConnError = (e: ApiError | null) => !!e && (e.code === 'NETWORK' || e.status >= 500) // ApiError(0, 'UNKNOWN') = lỗi mã phía trình duyệt, không phải mất kết nối

// ---- Tạm dừng polling khi không ai nhìn thấy ----------------------------------------------------------
// Cửa sổ nhúng bị thu nhỏ / bị che (trang bao ngoài báo qua logection:visible) hoặc tab trình duyệt đang ẩn → ngừng làm mới
// dữ liệu màn hình; hiện lại → tải ngay. Lý do: trên Render miễn phí, nhiều cửa sổ cùng polling làm cạn kết nối DB (13/11).
let hostHidden = false
const resumers = new Set<() => void>()
export function setHostHidden(hidden: boolean) {
  const was = hostHidden
  hostHidden = hidden
  if (was && !hidden) resumers.forEach((f) => f())
}
export const pollPaused = () => hostHidden || (typeof document !== 'undefined' && document.visibilityState === 'hidden')
/** Gọi `f` khi vừa hết bị ẩn (cửa sổ hiện lại hoặc tab trình duyệt hiện lại). */
export function onResume(f: () => void): () => void {
  resumers.add(f)
  const vis = () => { if (!pollPaused()) f() }
  document.addEventListener('visibilitychange', vis)
  return () => { resumers.delete(f); document.removeEventListener('visibilitychange', vis) }
}
