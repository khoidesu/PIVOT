import { useCallback, useEffect, useRef, useState } from 'react'
import { SimBadge, TopBar } from './components/TopBar'
import { HeroArt } from './components/HeroArt'
import { Icon } from './components/Icon'
import { useAutoEnter, useNavIndicator } from './motion'
import { EmbedBridge } from './components/EmbedBridge'
import { ErrorNote, Loading } from './components/ui'
import { I18nProvider, useI18n } from './i18n'
import { Benefits } from './screens/Benefits'
import { Confirm } from './screens/Confirm'
import { Demo } from './screens/Demo'
import { navFor, allowedRoute, defaultRoute, type Route } from './nav'
import { Workspace } from './screens/Workspace'
import { Landing } from './screens/Landing'
import { Docks } from './screens/Docks'
import { Exceptions } from './screens/Exceptions'
import { Fleet } from './screens/Fleet'
import { Recommend } from './screens/Recommend'
import { Request } from './screens/Request'
import { Timeline } from './screens/Timeline'
import { Tracking } from './screens/Tracking'
import { EMBED } from './api'
import { AppProvider, useApp } from './store'

const ROUTES: Route[] = ['request', 'fleet', 'recommend', 'confirm', 'timeline', 'benefits', 'demo', 'tracking', 'exceptions', 'docks']

function useHashRoute(): [Route, URLSearchParams, (to: string) => void] {
  const read = () => {
    const [path, qs] = window.location.hash.replace(/^#\/?/, '').split('?')
    return { route: (ROUTES as string[]).includes(path) ? (path as Route) : null, query: new URLSearchParams(qs ?? '') }
  }
  const [state, setState] = useState(read)
  useEffect(() => {
    const on = () => setState(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const go = useCallback((to: string) => { window.location.hash = `#${to}` }, [])
  return [state.route ?? 'request', state.query, go]
}

function Shell() {
  const { t, lang } = useI18n()
  const { fatal, session, me } = useApp()
  const [wanted, query, go] = useHashRoute()
  const role = me?.role ?? session?.role
  const route: Route = allowedRoute(role, wanted) ? wanted : defaultRoute(role) // đường dẫn không được phép → về mục mặc định
  useEffect(() => { document.documentElement.lang = lang }, [lang])
  useEffect(() => { document.documentElement.classList.toggle('embed', EMBED) }, [])
  useEffect(() => { window.scrollTo(0, 0) }, [route])
  const shell = useRef<HTMLDivElement>(null)
  const navEl = useRef<HTMLDivElement>(null)
  const indEl = useRef<HTMLSpanElement>(null)
  useAutoEnter(shell, [!!session])                                            // thẻ/ghi chú/menu mới xuất hiện trượt nhẹ vào (GSAP)
  useNavIndicator(navEl, indEl, [route, lang, role, !!session])    // viên chỉ mục trượt tới mục đang chọn
  if (!session) return <main><Loading /></main> // chỉ xảy ra trong cửa sổ nhúng, lúc chờ trang bao ngoài đưa phiên vào
  const today = new Date().toLocaleDateString(lang === 'vi' ? 'vi-VN' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  return (
    <div ref={shell}>
      {EMBED && <EmbedBridge />}
      <header className="hero">
        <HeroArt />
        <div className="hero-top">
          <nav className="nav" aria-label="Menu" ref={navEl}>
            <span className="nav-ind" aria-hidden ref={indEl} />
            {navFor(role).map((r) => (
              <a key={r} href={`#/${r}`} aria-current={route === r ? 'page' : undefined}>{t(r === 'fleet' ? `nav.fleet.${role}` : `nav.${r}`)}</a>))}
          </nav>
          <TopBar />
        </div>
        <div className="hero-main">
          <div>
            <span className="hero-eyebrow"><Icon name="pin" size={14} />{role ? t(`role.${role}`) : ''}</span>
            <div className="hero-title">{me?.org_name ?? session.name}</div>
          </div>
          <div className="hero-side"><span className="row"><Icon name="calendar" size={14} />{today}</span><SimBadge /></div>
        </div>
      </header>
      <main>
        {fatal && <ErrorNote error={fatal} />}
        {route === 'request' && <Request go={go} query={query} />}
        {route === 'fleet' && <Fleet go={go} />}
        {route === 'recommend' && <Recommend go={go} query={query} />}
        {route === 'confirm' && <Confirm />}
        {route === 'tracking' && <Tracking query={query} />}
        {route === 'docks' && <Docks />}
        {route === 'exceptions' && <Exceptions go={go} />}
        {route === 'timeline' && <Timeline query={query} />}
        {route === 'benefits' && <Benefits query={query} />}
        {route === 'demo' && <Demo />}
      </main>
    </div>
  )
}

const ENTERED = 'pivot.entered'
/** Trang ngoài: lần đầu vào tab thấy trang mở đầu; bấm Bắt đầu → khu làm việc (nhớ trong tab). Tab đã có cửa sổ thì vào thẳng. */
function Outer() {
  const [entered, setEntered] = useState(() => { try { return sessionStorage.getItem(ENTERED) === '1' || !!sessionStorage.getItem('pivot.workspace') } catch { return true } })
  const set = (v: boolean) => { setEntered(v); try { v ? sessionStorage.setItem(ENTERED, '1') : sessionStorage.removeItem(ENTERED) } catch { /* bỏ qua */ } window.scrollTo(0, 0) }
  return entered ? <Workspace onHome={() => set(false)} /> : <Landing onStart={() => set(true)} />
}

export default function App() {
  return <I18nProvider>{EMBED ? <AppProvider><Shell /></AppProvider> : <Outer />}</I18nProvider>
}
