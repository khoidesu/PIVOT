import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, getSession, setOnUnauthorized, setSession, type Location, type Me, type Meta, type Role, type Session } from './api'
import { setServerTime } from './fmt'

interface AppCtx {
  session: Session | null // mỗi tab một người (sessionStorage)
  me: Me | null
  meta: Meta | null
  locations: Location[]
  epoch: number // tăng khi đăng nhập / làm mới → các màn hình tải lại
  fatal: ApiError | null
  notice: 'expired' | null
  login: (name: string, role: Role) => Promise<void>
  logout: () => void
  bump: () => void
  syncClock: () => void // chỉ cập nhật lệch giờ server, không tải lại màn hình
}

const Ctx = createContext<AppCtx | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<Session | null>(getSession())
  const [me, setMe] = useState<Me | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [locations, setLocations] = useState<Location[]>([])
  const [epoch, setEpoch] = useState(0)
  const [fatal, setFatal] = useState<ApiError | null>(null)
  const [notice, setNotice] = useState<'expired' | null>(null)

  const clear = useCallback(() => { setMe(null); setMeta(null); setLocations([]); setFatal(null) }, [])
  useEffect(() => { // 401 ở bất kỳ API nào → về màn hình đăng nhập kèm thông báo
    setOnUnauthorized(() => { setSessionState(null); clear(); setNotice('expired') })
    return () => setOnUnauthorized(null)
  }, [clear])

  const load = useCallback(async () => {
    if (!getSession()) return
    try {
      const [m, mt, locs] = await Promise.all([api.me(), api.meta(), api.locations()])
      setServerTime(mt.server_time)
      setMe(m); setMeta(mt); setLocations(locs); setFatal(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return // đã được xử lý bởi onUnauthorized
      setFatal(e instanceof ApiError ? e : new ApiError(0, 'NETWORK', String(e)))
    }
  }, [])

  useEffect(() => { void load() }, [load, epoch, session])

  const value = useMemo<AppCtx>(() => ({
    session, me, meta, locations, epoch, fatal, notice,
    login: async (name, role) => {
      const r = await api.login(name, role) // lỗi (tên/vai trò sai…) ném ra cho màn hình đăng nhập hiển thị
      const s: Session = { token: r.token, name: r.me.user_name, role: r.me.role as Role }
      setSession(s); setSessionState(s); setNotice(null); setMe(r.me); setEpoch((n) => n + 1)
    },
    logout: () => { setSession(null); setSessionState(null); clear(); setNotice(null) },
    bump: () => setEpoch((n) => n + 1),
    syncClock: () => { api.meta().then((mt) => { setServerTime(mt.server_time); setMeta(mt) }).catch(() => {}) },
  }), [session, me, meta, locations, epoch, fatal, notice, clear])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp outside AppProvider')
  return v
}
