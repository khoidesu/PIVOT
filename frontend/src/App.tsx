import { useCallback, useEffect, useState } from 'react'
import { TopBar } from './components/TopBar'
import { ErrorNote } from './components/ui'
import { I18nProvider, useI18n } from './i18n'
import { Benefits } from './screens/Benefits'
import { Confirm } from './screens/Confirm'
import { Demo } from './screens/Demo'
import { Login } from './screens/Login'
import { Fleet } from './screens/Fleet'
import { Recommend } from './screens/Recommend'
import { Request } from './screens/Request'
import { Timeline } from './screens/Timeline'
import { AppProvider, useApp } from './store'

const ROUTES = ['request', 'fleet', 'recommend', 'confirm', 'timeline', 'benefits', 'demo'] as const
type Route = (typeof ROUTES)[number]

function useHashRoute(): [Route, URLSearchParams, (to: string) => void] {
  const read = () => {
    const [path, qs] = window.location.hash.replace(/^#\/?/, '').split('?')
    return { route: (ROUTES as readonly string[]).includes(path) ? (path as Route) : 'request', query: new URLSearchParams(qs ?? '') }
  }
  const [state, setState] = useState(read)
  useEffect(() => {
    const on = () => setState(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const go = useCallback((to: string) => { window.location.hash = `#${to}` }, [])
  return [state.route, state.query, go]
}

function Shell() {
  const { t, lang } = useI18n()
  const { fatal, session } = useApp()
  const [route, query, go] = useHashRoute()
  useEffect(() => { document.documentElement.lang = lang }, [lang])
  useEffect(() => { window.scrollTo(0, 0) }, [route])
  if (!session) return <Login />
  return (
    <>
      <TopBar />
      <nav className="nav-wrap" aria-label="Screens">
        <div className="nav">
          {ROUTES.map((r) => (
            <a key={r} href={`#/${r}`} aria-current={route === r ? 'page' : undefined}>{t(`nav.${r}`)}</a>))}
        </div>
      </nav>
      <main>
        {fatal && <ErrorNote error={fatal} />}
        {route === 'request' && <Request go={go} query={query} />}
        {route === 'fleet' && <Fleet go={go} />}
        {route === 'recommend' && <Recommend go={go} query={query} />}
        {route === 'confirm' && <Confirm />}
        {route === 'timeline' && <Timeline query={query} />}
        {route === 'benefits' && <Benefits query={query} />}
        {route === 'demo' && <Demo />}
      </main>
    </>
  )
}

export default function App() {
  return <I18nProvider><AppProvider><Shell /></AppProvider></I18nProvider>
}
