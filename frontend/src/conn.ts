import type { ApiError } from './api'

/** Nhịp tự thử lại khi lỗi mà màn không polling (QA-07): mất kết nối rồi API sống lại thì tự hồi, không cần chuyển màn. */
export const RETRY_MS = 4000

/** Lỗi do mất kết nối / máy chủ không trả lời (khác lỗi nghiệp vụ 4xx). */
export const isConnError = (e: ApiError | null) => !!e && (e.code === 'NETWORK' || e.status >= 500) // ApiError(0, 'UNKNOWN') = lỗi mã phía trình duyệt, không phải mất kết nối
