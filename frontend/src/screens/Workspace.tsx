import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, getSession, setSession, type Role } from '../api'
import { Brand } from '../components/TopBar'
import { Chip, ErrorNote } from '../components/ui'
import { useI18n } from '../i18n'
import {
  addWin, CHAIN, closeWin, EMPTY, focusWin, MAX_WINS, minimizeWin, moveWin, parse, placement, serialize, setLayout, TEAM, updateToken,
  winId, WsLimitError, type LayoutMode, type Win, type WsState,
} from '../workspace'
import { LoginForm } from './Login'

const KEY = 'pivot.workspace'
const LAYOUTS: LayoutMode[] = ['grid', 'cols', 'focus']

function initial(): WsState {
  let s = EMPTY
  try { s = parse(sessionStorage.getItem(KEY)) } catch { /* sessionStorage có thể bị chặn */ }
  const old = getSession() // phiên một-người của bản cũ → trở thành cửa sổ đầu tiên
  if (!s.wins.length && old) { s = addWin(s, { id: winId(old.name, old.role), name: old.name, role: old.role, token: old.token }); setSession(null) }
  return s
}

export function Workspace() {
  const { t, lang, setLang } = useI18n()
  const [st, setSt] = useState<WsState>(initial)
  const stRef = useRef(st)
  const [badges, setBadges] = useState<Record<string, number>>({})
  const [expired, setExpired] = useState<Record<string, boolean>>({})
  const [pop, setPop] = useState<'closed' | 'list' | 'form'>('closed')
  const [err, setErr] = useState<ApiError | null>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)
  const [width, setWidth] = useState(1200)
  const frames = useRef(new Map<string, HTMLIFrameElement>())
  const gridEl = useRef<HTMLDivElement | null>(null)
  const popEl = useRef<HTMLDivElement | null>(null)

  const commit = useCallback((next: WsState) => { stRef.current = next; setSt(next) }, [])
  useEffect(() => { try { sessionStorage.setItem(KEY, serialize(st)) } catch { /* bỏ qua */ } }, [st])

  const sendSession = useCallback((id: string) => {
    const w = stRef.current.wins.find((x) => x.id === id)
    const f = frames.current.get(id)
    if (w && f?.contentWindow) f.contentWindow.postMessage({ type: 'logection:session', session: { token: w.token, name: w.name, role: w.role } }, location.origin)
  }, [])

  const relogin = useCallback(async (w: Win) => { // phiên hết hạn (vd dữ liệu vừa reset): đăng nhập lại đúng tên + vai trò
    try {
      const r = await api.login(w.name, w.role)
      commit(updateToken(stRef.current, w.id, r.token))
      setExpired((e) => ({ ...e, [w.id]: false }))
      sendSession(w.id)
    } catch { setExpired((e) => ({ ...e, [w.id]: true })) }
  }, [commit, sendSession])

  useEffect(() => { // thư từ các cửa sổ: bắt tay, số việc chờ, đăng xuất, phiên hết hạn
    const on = (e: MessageEvent) => {
      const d = e.data as { type?: string; n?: number } | null
      if (e.origin !== location.origin || !d?.type?.startsWith('logection:')) return
      const hit = [...frames.current].find(([, f]) => f.contentWindow === e.source)
      if (!hit) return
      const id = hit[0]
      if (d.type === 'logection:ready') { sendSession(id); hit[1].contentWindow?.postMessage({ type: 'logection:lang', lang }, location.origin) }
      else if (d.type === 'logection:badge') setBadges((b) => (b[id] === d.n ? b : { ...b, [id]: d.n ?? 0 }))
      else if (d.type === 'logection:logout') commit(closeWin(stRef.current, id))
      else if (d.type === 'logection:expired') { const w = stRef.current.wins.find((x) => x.id === id); if (w) void relogin(w) }
    }
    window.addEventListener('message', on)
    return () => window.removeEventListener('message', on)
  }, [commit, relogin, sendSession, lang])

  useEffect(() => { for (const f of frames.current.values()) f.contentWindow?.postMessage({ type: 'logection:lang', lang }, location.origin) }, [lang])

  useEffect(() => { // bấm vào bên trong một cửa sổ (khung nhúng) → cửa sổ đó thành tiêu điểm
    const on = () => setTimeout(() => {
      const a = document.activeElement
      const hit = a instanceof HTMLIFrameElement ? [...frames.current].find(([, f]) => f === a) : undefined
      if (hit && stRef.current.focus !== hit[0]) commit(focusWin(stRef.current, hit[0]))
    }, 0)
    window.addEventListener('blur', on)
    return () => window.removeEventListener('blur', on)
  }, [commit])

  useEffect(() => { // đo bề rộng vùng cửa sổ để tự chia cột
    const el = gridEl.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el); setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [st.wins.length === 0])

  useEffect(() => { // đóng ngăn "Thêm người" khi bấm ra ngoài / Escape
    if (pop === 'closed') return
    const out = (e: MouseEvent) => { if (!popEl.current?.contains(e.target as Node)) setPop('closed') }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setPop('closed') }
    document.addEventListener('mousedown', out); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', out); document.removeEventListener('keydown', esc) }
  }, [pop])

  async function enter(name: string, role: Role) {
    const r = await api.login(name, role)
    try { commit(addWin(stRef.current, { id: winId(r.me.user_name, role), name: r.me.user_name, role, token: r.token })) }
    catch (e) { if (e instanceof WsLimitError) throw new ApiError(0, 'WS_LIMIT', t('ws.limit', { n: MAX_WINS })); throw e }
  }
  async function quick(name: string, role: Role) {
    setErr(null)
    try { await enter(name, role); setPop('closed') } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
  }
  async function chain() {
    setErr(null)
    try { for (const p of CHAIN) await enter(p.name, p.role); setPop('closed') } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
  }

  const wins = st.wins
  const open = wins.filter((w) => w.open)
  const place = placement(st, width)
  const narrow = width < 640
  const stable = [...wins].sort((a, b) => (a.id < b.id ? -1 : 1)) // thứ tự DOM cố định (đổi thứ tự DOM sẽ làm khung nhúng tải lại); thứ tự hiển thị dùng CSS `order`
  const focusId = st.focus ?? open[0]?.id

  if (!wins.length) {
    return (
      <main className="login">
        <div className="login-top">
          <Brand />
          <div className="row">
            <Chip kind="sim">● {t('badge.mock')}</Chip>
            <div className="seg" role="group" aria-label="Language">
              {(['vi', 'en'] as const).map((l) => <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
            </div>
          </div>
        </div>
        <LoginForm onLogin={enter} />
      </main>
    )
  }

  return (
    <div className="ws">
      <nav className="ws-rail" aria-label={t('ws.rail')}>
        <div className="ws-nodes">
          {wins.map((w) => {
            const b = badges[w.id] ?? 0
            const isOpen = w.open
            return (
              <button key={w.id} className={`ws-node role-${w.role}${isOpen ? '' : ' bg'}${isOpen && w.id === focusId ? ' foc' : ''}`}
                title={`${w.name} · ${t(`role.${w.role}`)} — ${isOpen ? t('ws.open') : t('ws.bgTip')}`}
                aria-label={`${w.name}, ${t(`role.${w.role}`)}, ${isOpen ? t('ws.open') : t('ws.bg')}${b ? `, ${t('ws.pending', { n: b })}` : ''}`}
                onClick={() => commit(focusWin(stRef.current, w.id))}>
                {w.name.trim().charAt(0).toUpperCase()}
                {b > 0 && <span className="ws-bd">{b > 9 ? '9+' : b}</span>}
              </button>)
          })}
        </div>
        <div className="ws-tools" ref={popEl}>
          <button className="ws-add" aria-label={t('ws.add')} aria-expanded={pop !== 'closed'} aria-haspopup="menu" onClick={() => { setErr(null); setPop(pop === 'closed' ? 'list' : 'closed') }}>+</button>
          {pop !== 'closed' && (
            <div className="ws-pop" role="menu">
              {pop === 'list' ? (
                <>
                  <div className="ws-pop-h">{t('ws.add')}</div>
                  {TEAM.map((p) => {
                    const ex = wins.find((w) => w.id === winId(p.name, p.role))
                    return (
                      <button key={p.name} role="menuitem" className="ws-pi" disabled={!!ex?.open} onClick={() => quick(p.name, p.role)}>
                        <span className={`ws-av role-${p.role}`}>{p.name.charAt(0)}</span>
                        <span className="grow">{p.name} <span className="muted">· {t(`role.${p.role}`)}</span></span>
                        {ex && <span className="muted small">{ex.open ? t('ws.open') : t('ws.bg')}</span>}
                      </button>)
                  })}
                  <div className="ws-sep" />
                  <button role="menuitem" className="ws-pi" onClick={chain}>{t('ws.chain')}</button>
                  <button role="menuitem" className="ws-pi" onClick={() => setPop('form')}>{t('ws.other')}</button>
                  {err && <ErrorNote error={err} />}
                </>
              ) : (
                <LoginForm compact onLogin={async (n, r) => { await enter(n, r); setPop('closed') }} />
              )}
            </div>)}
        </div>
      </nav>

      <section className="ws-work">
        <div className="ws-bar">
          <span className="muted">{t('ws.count', { n: open.length })}{wins.length > open.length ? ` · ${t('ws.bgN', { n: wins.length - open.length })}` : ''}</span>
          <span className="grow" />
          <div className="seg" role="group" aria-label={t('ws.layout')}>
            {LAYOUTS.map((l) => <button key={l} aria-pressed={st.layout === l} onClick={() => commit(setLayout(stRef.current, l))}>{t(`ws.layout.${l}`)}</button>)}
          </div>
          <div className="seg" role="group" aria-label="Language">
            {(['vi', 'en'] as const).map((l) => <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
          </div>
        </div>
        <div ref={gridEl} className={`ws-grid${dragId ? ' dragging' : ''}`} style={narrow ? { gridTemplateColumns: 'minmax(0, 1fr)', gridTemplateRows: 'minmax(0, 1fr)' } : { gridTemplateColumns: place.columns, gridTemplateRows: place.rows }}>
          {!open.length && <div className="ws-none">{t('ws.empty')}</div>}
          {stable.map((w) => {
            const p = place.items[w.id]
            const shown = w.open && (!narrow || w.id === focusId)
            const b = badges[w.id] ?? 0
            return (
              <div key={w.id} className={`ws-win role-${w.role}${w.id === focusId ? ' foc' : ''}${overId === w.id && dragId !== w.id ? ' over' : ''}`}
                style={{ display: shown ? undefined : 'none', ...(narrow ? {} : { order: p?.order ?? 0, gridColumn: p?.gridColumn, gridRow: p?.gridRow }) }}
                onDragOver={(e) => { if (dragId) { e.preventDefault(); setOverId(w.id) } }}
                onDrop={(e) => { e.preventDefault(); if (dragId) commit(moveWin(stRef.current, dragId, w.id)); setDragId(null); setOverId(null) }}>
                <div className="ws-stripe" />
                <div className="ws-wh" draggable title={t('ws.drag')} onClick={() => commit(focusWin(stRef.current, w.id))}
                  onDragStart={(e) => { setDragId(w.id); e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', w.id) } catch { /* bỏ qua */ } }}
                  onDragEnd={() => { setDragId(null); setOverId(null) }}>
                  <span className="ws-grip" aria-hidden>⠿</span>
                  <span className="ws-title"><b>{w.name}</b> <span className="muted">· {t(`role.${w.role}`)}</span>{b > 0 && <span className="ws-pend">{t('ws.pending', { n: b })}</span>}</span>
                  <button className="ws-ib" aria-label={`${t('ws.min')} — ${w.name}`} title={t('ws.min')} onClick={(e) => { e.stopPropagation(); commit(minimizeWin(stRef.current, w.id)) }}>–</button>
                  <button className="ws-ib" aria-label={`${t('ws.close')} — ${w.name}`} title={t('ws.close')} onClick={(e) => { e.stopPropagation(); commit(closeWin(stRef.current, w.id)) }}>×</button>
                </div>
                <div className="ws-frame">
                  <iframe title={t('ws.win', { name: w.name })} src={`${location.pathname}?embed=1`} ref={(el) => { if (el) frames.current.set(w.id, el); else frames.current.delete(w.id) }} />
                  {expired[w.id] && (
                    <div className="ws-expired">
                      <span>{t('login.expired')}</span>
                      <button className="btn sm primary" onClick={() => void relogin(w)}>{t('ws.relogin')}</button>
                    </div>)}
                </div>
              </div>)
          })}
        </div>
      </section>
    </div>
  )
}
