import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api'
import { useApp } from './store'

/** Tải dữ liệu theo vai trò hiện tại; tải lại khi đổi vai trò. pollMs > 0 → polling (DRAFT: polling trước, SSE nếu cần). */
export function useData<T>(fetcher: () => Promise<T>, pollMs = 0) {
  const { epoch } = useApp()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher

  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      setData(await fetchRef.current()); setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e)))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { setData(null); void reload() }, [epoch, reload])
  useEffect(() => {
    if (!pollMs) return
    const id = setInterval(() => { void reload(true) }, pollMs)
    return () => clearInterval(id)
  }, [pollMs, reload])
  return { data, error, loading, reload }
}
