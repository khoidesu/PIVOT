import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, getUser, setUser as persistUser, type Location, type Me, type Meta, type UserKey } from './api'
import { setServerTime } from './fmt'

interface AppCtx {
  user: UserKey
  me: Me | null
  meta: Meta | null
  locations: Location[]
  epoch: number // tăng khi đổi vai trò / làm mới → các màn hình tải lại
  fatal: ApiError | null
  switchUser: (u: UserKey) => void
  bump: () => void
  syncClock: () => void // chỉ cập nhật lệch giờ server, không tải lại màn hình
}

const Ctx = createContext<AppCtx | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<UserKey>(getUser())
  const [me, setMe] = useState<Me | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [locations, setLocations] = useState<Location[]>([])
  const [epoch, setEpoch] = useState(0)
  const [fatal, setFatal] = useState<ApiError | null>(null)

  const load = useCallback(async () => {
    try {
      const [m, mt, locs] = await Promise.all([api.me(), api.meta(), api.locations()])
      setServerTime(mt.server_time)
      setMe(m); setMeta(mt); setLocations(locs); setFatal(null)
    } catch (e) {
      setFatal(e instanceof ApiError ? e : new ApiError(0, 'NETWORK', String(e)))
    }
  }, [])

  useEffect(() => { void load() }, [load, epoch, user])

  const value = useMemo<AppCtx>(() => ({
    user, me, meta, locations, epoch, fatal,
    switchUser: (u) => { persistUser(u); setUserState(u); setEpoch((n) => n + 1) },
    bump: () => setEpoch((n) => n + 1),
    syncClock: () => { api.meta().then((mt) => { setServerTime(mt.server_time); setMeta(mt) }).catch(() => {}) },
  }), [user, me, meta, locations, epoch, fatal])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp outside AppProvider')
  return v
}
