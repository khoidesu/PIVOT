import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, EMBED, getSession, setOnUnauthorized, setSession, type FleetRefresh, type Location, type Me, type Meta, type Role, type Session } from './api'
import { setServerTime } from './fmt'

interface AppCtx {
  session: Session | null // mỗi tab một người (sessionStorage)
  me: Me | null
  meta: Meta | null
  locations: Location[]
  epoch: number // tăng khi đăng nhập / làm mới → các màn hình tải lại
  fatal: ApiError | null
  notice: 'expired' | null
  fleetSync: { n: number; at: string } | null // lần làm tươi vị trí đội xe gần nhất (chỉ nhà vận tải)
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
  const [fleetSync, setFleetSync] = useState<{ n: number; at: string } | null>(null)

  const clear = useCallback(() => { setMe(null); setMeta(null); setLocations([]); setFatal(null) }, [])
  useEffect(() => { // 401 ở bất kỳ API nào → về màn hình đăng nhập kèm thông báo (trong cửa sổ nhúng: nhờ trang bao ngoài đăng nhập lại)
    setOnUnauthorized(() => {
      setSessionState(null); clear()
      if (EMBED) window.parent.postMessage({ type: 'logection:expired' }, location.origin)
      else setNotice('expired')
    })
    return () => setOnUnauthorized(null)
  }, [clear])

  useEffect(() => { // cửa sổ nhúng: xin phiên từ trang bao ngoài (bắt tay), nhận lại khi token đổi
    if (!EMBED) return
    const on = (e: MessageEvent) => {
      if (e.origin !== location.origin || e.source !== window.parent) return
      const d = e.data as { type?: string; session?: Session } | null
      if (d?.type !== 'logection:session' || !d.session) return
      setSession(d.session); setSessionState(d.session); setNotice(null); setEpoch((n) => n + 1)
    }
    window.addEventListener('message', on)
    window.parent.postMessage({ type: 'logection:ready' }, location.origin)
    return () => window.removeEventListener('message', on)
  }, [])

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

  // Nhà vận tải: tự làm tươi vị trí + khung rảnh của xe rảnh khi vào và định kỳ (< ngưỡng quá hạn 5 phút) — bỏ qua khi tab đang ẩn.
  const role = me?.role
  useEffect(() => {
    if (role !== 'carrier') { setFleetSync(null); return }
    let stop = false
    const run = () => {
      if (document.visibilityState === 'hidden') return
      api.refreshFleet().then((r: FleetRefresh) => { if (!stop) setFleetSync({ n: r.updated + r.already_fresh, at: r.at }) }).catch(() => { /* không chặn giao diện */ })
    }
    run()
    const id = setInterval(run, 2 * 60 * 1000)
    document.addEventListener('visibilitychange', run)
    return () => { stop = true; clearInterval(id); document.removeEventListener('visibilitychange', run) }
  }, [role, me?.user_id, epoch])

  const value = useMemo<AppCtx>(() => ({
    session, me, meta, locations, epoch, fatal, notice, fleetSync,
    login: async (name, role) => {
      const r = await api.login(name, role) // lỗi (tên/vai trò sai…) ném ra cho màn hình đăng nhập hiển thị
      const s: Session = { token: r.token, name: r.me.user_name, role: r.me.role as Role }
      setSession(s); setSessionState(s); setNotice(null); setMe(r.me); setEpoch((n) => n + 1)
    },
    logout: () => { setSession(null); setSessionState(null); clear(); setNotice(null); if (EMBED) window.parent.postMessage({ type: 'logection:logout' }, location.origin) },
    bump: () => setEpoch((n) => n + 1),
    syncClock: () => { api.meta().then((mt) => { setServerTime(mt.server_time); setMeta(mt) }).catch(() => {}) },
  }), [session, me, meta, locations, epoch, fatal, notice, fleetSync, clear])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp outside AppProvider')
  return v
}
