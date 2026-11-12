import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api'
import { latestGuard } from './latest'
import { useApp } from './store'

/** Tải dữ liệu theo vai trò hiện tại; tải lại khi đổi vai trò hoặc khi `key` đổi (vd id chuyến đang xem).
 *  pollMs > 0 → polling (DRAFT: polling trước, SSE nếu cần). Chỉ kết quả của lần gọi mới nhất được áp dụng. */
export function useData<T>(fetcher: () => Promise<T>, pollMs = 0, key: unknown = null) {
  const { epoch } = useApp()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher
  const guard = useRef(latestGuard())

  const reload = useCallback(async (silent = false) => {
    const id = guard.current.next()
    if (!silent) setLoading(true)
    try {
      const d = await fetchRef.current()
      if (!guard.current.current(id)) return // đã có lần gọi mới hơn (đổi vai trò/chuyến, hoặc polling chồng): bỏ kết quả cũ
      setData(d); setError(null)
    } catch (e) {
      if (!guard.current.current(id)) return
      setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e)))
    } finally {
      if (guard.current.current(id)) setLoading(false)
    }
  }, [])

  useEffect(() => { setData(null); void reload() }, [epoch, reload, key])
  useEffect(() => {
    if (!pollMs) return
    const id = setInterval(() => { void reload(true) }, pollMs)
    return () => clearInterval(id)
  }, [pollMs, reload])
  return { data, error, loading, reload }
}
