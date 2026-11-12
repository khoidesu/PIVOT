import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, getSession, setSession, type Role } from '../api'
import { Chip, ErrorNote } from '../components/ui'
import { Icon } from '../components/Icon'
import { HeroArt } from '../components/HeroArt'
import { Brand } from '../components/TopBar'
import { gsap, reducedMotion, useAutoEnter, useGSAP } from '../motion'
import { useI18n } from '../i18n'
import {
  addWin, CHAIN, closeWin, EMPTY, focusWin, MAX_WINS, minimizeWin, moveWin, parse, placement, resetSizes, serialize, dragSplit, TEAM, updateToken,
  winId, WsLimitError, type Splitter, type Win, type WsState,
} from '../workspace'
import { applyTheme, currentTheme, type Theme } from '../theme'
import { LoginForm } from './Login'

const KEY = 'pivot.workspace'
const GAP = 10 // px giữa các khung (cũng là bề rộng vùng bắt của thanh kéo)
/** Chữ viết tắt trong avatar: 2 chữ cái đầu của hai từ cuối ("Nguyễn Văn An" → VA), một từ → chữ đầu + chữ thứ hai. */
const initials = (name: string) => {
  const w = name.trim().split(/\s+/)
  return (w.length > 1 ? w[w.length - 2][0] + w[w.length - 1][0] : name.trim().slice(0, 2)).toUpperCase()
}

function initial(): WsState {
  let s = EMPTY
  try { s = parse(sessionStorage.getItem(KEY)) } catch { /* sessionStorage có thể bị chặn */ }
  const old = getSession() // phiên một-người của bản cũ → trở thành cửa sổ đầu tiên
  if (!s.wins.length && old) { s = addWin(s, { id: winId(old.name, old.role), name: old.name, role: old.role, token: old.token }); setSession(null) }
  return s
}

export function Workspace({ onHome }: { onHome?: () => void }) {
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
  const [theme, setThemeState] = useState<Theme>(currentTheme)
  const [splitting, setSplitting] = useState<'col' | 'row' | null>(null)
  const root = useRef<HTMLDivElement>(null)
  useAutoEnter(root)                                                   // cửa sổ mới / ngăn thêm người hiện lên mượt (GSAP)
  const started = st.wins.length > 0
  useGSAP(() => {                                                      // màn bắt đầu: chữ và bảng chọn vai vào lần lượt
    if (started || reducedMotion()) return
    gsap.timeline({ defaults: { duration: 0.7 } })
      .from('.ws-hero-copy > *', { opacity: 0, y: 28, stagger: 0.09 }, 0.15)
      .from('.ws-start-card', { opacity: 0, y: 24, scale: 0.98 }, 0.35)
      .from('.ws-rail, .ws-bar', { opacity: 0, duration: 0.5 }, 0)
  }, { scope: root, dependencies: [started] })
  const [slim, setSlim] = useState(() => { try { return localStorage.getItem('pivot.railSlim') === '1' } catch { return false } }) // thanh người: rộng (có tên) hoặc thu gọn (chỉ avatar)
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
      if (d.type === 'logection:ready') { sendSession(id); hit[1].contentWindow?.postMessage({ type: 'logection:lang', lang }, location.origin); hit[1].contentWindow?.postMessage({ type: 'logection:theme', theme }, location.origin) }
      else if (d.type === 'logection:badge') setBadges((b) => (b[id] === d.n ? b : { ...b, [id]: d.n ?? 0 }))
      else if (d.type === 'logection:logout') commit(closeWin(stRef.current, id))
      else if (d.type === 'logection:expired') { const w = stRef.current.wins.find((x) => x.id === id); if (w) void relogin(w) }
    }
    window.addEventListener('message', on)
    return () => window.removeEventListener('message', on)
  }, [commit, relogin, sendSession, lang, theme])

  useEffect(() => { for (const f of frames.current.values()) f.contentWindow?.postMessage({ type: 'logection:lang', lang }, location.origin) }, [lang])
  useEffect(() => { // chế độ sáng/tối: áp dụng cho trang bao ngoài và phát tới mọi cửa sổ nhúng
    applyTheme(theme)
    for (const f of frames.current.values()) f.contentWindow?.postMessage({ type: 'logection:theme', theme }, location.origin)
  }, [theme])
  const setTheme = (th: Theme) => { applyTheme(th, true); setThemeState(th) }

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

  /** Kéo thanh chia: đổi tỉ lệ hai khung kề nhau theo quãng chuột đi (tính bằng phần của hàng/vùng). Khung nhúng tạm không nhận chuột để không "nuốt" sự kiện. */
  function startSplit(e: React.PointerEvent<HTMLDivElement>, sp: Splitter) {
    const el = gridEl.current
    if (!el) return
    e.preventDefault()
    const box = el.getBoundingClientRect()
    let last = sp.kind === 'col' ? e.clientX : e.clientY
    const target = e.currentTarget
    target.setPointerCapture(e.pointerId)
    setSplitting(sp.kind)
    const move = (ev: PointerEvent) => {
      const now = sp.kind === 'col' ? ev.clientX : ev.clientY
      const delta = (now - last) / (sp.kind === 'col' ? box.width : box.height)
      if (!delta) return
      const next = dragSplit(stRef.current, width, sp, delta)
      if (next !== stRef.current) { last = now; commit(next) }
    }
    const up = () => { target.removeEventListener('pointermove', move); target.removeEventListener('pointerup', up); target.removeEventListener('pointercancel', up); setSplitting(null) }
    target.addEventListener('pointermove', move); target.addEventListener('pointerup', up); target.addEventListener('pointercancel', up)
  }

  const wins = st.wins
  const open = wins.filter((w) => w.open)
  const place = placement(st, width)
  const narrow = width < 640
  const stable = [...wins].sort((a, b) => (a.id < b.id ? -1 : 1)) // thứ tự DOM cố định (đổi thứ tự DOM sẽ làm khung nhúng tải lại); thứ tự hiển thị dùng CSS `order`
  const focusId = st.focus ?? open[0]?.id

  const addMenu = pop === 'form' ? (
    <LoginForm compact onLogin={async (n, r) => { await enter(n, r); setPop('closed') }} />
  ) : (
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
  )

  return (
    <div className="ws" ref={root}>
      <nav className={`ws-rail${slim ? ' slim' : ''}`} aria-label={t('ws.rail')}>
        <div className="ws-rail-h">
          <button className="brand-btn" aria-label="LOGECTION" onClick={onHome}><Brand /></button>
          <button className="ws-collapse" aria-label={t(slim ? 'ws.expand' : 'ws.collapse')} title={t(slim ? 'ws.expand' : 'ws.collapse')} aria-expanded={!slim}
            onClick={() => { setSlim(!slim); try { localStorage.setItem('pivot.railSlim', slim ? '0' : '1') } catch { /* bỏ qua */ } }}><Icon name={slim ? 'chevronsRight' : 'chevronsLeft'} size={16} /></button>
        </div>
        {!slim && <span className="ws-rail-t">{t('ws.people')}</span>}
        <div className="ws-nodes">
          {wins.map((w) => {
            const b = badges[w.id] ?? 0
            const isOpen = w.open
            const label = `${w.name} · ${t(`role.${w.role}`)}`
            return (
              <button key={w.id} className={`ws-node role-${w.role}${isOpen ? '' : ' bg'}${isOpen && w.id === focusId ? ' foc' : ''}`}
                title={`${label} — ${isOpen ? t('ws.open') : t('ws.bgTip')}`}
                aria-label={`${w.name}, ${t(`role.${w.role}`)}, ${isOpen ? t('ws.open') : t('ws.bg')}${b ? `, ${t('ws.pending', { n: b })}` : ''}`}
                onClick={() => commit(focusWin(stRef.current, w.id))}>
                <span className="ws-ava" aria-hidden>{initials(w.name)}{b > 0 && slim && <span className="ws-bd">{b > 9 ? '9+' : b}</span>}</span>
                {!slim && (
                  <span className="ws-meta">
                    <b>{w.name}</b>
                    <small><i className={isOpen ? 'on' : ''} aria-hidden />{t(`role.${w.role}`)}</small>
                  </span>)}
                {!slim && b > 0 && <span className="ws-pill">{b > 9 ? '9+' : b}</span>}
              </button>)
          })}
        </div>
        <div className="ws-tools" ref={popEl}>
          <button className="ws-add" aria-label={t('ws.add')} title={t('ws.add')} aria-expanded={pop !== 'closed'} aria-haspopup="menu" onClick={() => { setErr(null); setPop(pop === 'closed' ? 'list' : 'closed') }}>
            <Icon name="plus" size={16} />{!slim && <span>{t('ws.add')}</span>}
          </button>
          <div className="seg ws-theme" role="group" aria-label={t('theme.label')}>
            {(['light', 'dark'] as const).map((m) => <button key={m} className="theme-btn" aria-pressed={theme === m} title={t(`theme.${m}`)} aria-label={t(`theme.${m}`)} onClick={() => setTheme(m)}><Icon name={m === 'light' ? 'sun' : 'moon'} size={15} /><span>{t(`theme.${m}`)}</span></button>)}
          </div>
          {pop !== 'closed' && (
            <div className="ws-pop" role="menu">
              {addMenu}
            </div>)}
        </div>
      </nav>

      <section className="ws-work">
        <div className="ws-bar">
          <span className="muted">{t('ws.count', { n: open.length })}{wins.length > open.length ? ` · ${t('ws.bgN', { n: wins.length - open.length })}` : ''}</span>
          <span className="grow" />
          {st.sizes && <button className="btn sm" onClick={() => commit(resetSizes(stRef.current))}>{t('ws.even')}</button>}
          <div className="seg" role="group" aria-label="Language">
            {(['vi', 'en'] as const).map((l) => <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
          </div>
        </div>
        <div ref={gridEl} className={`ws-grid${dragId || splitting ? ' dragging' : ''}${splitting ? ` splitting-${splitting}` : ''}`}>
          {!wins.length
            ? (
              <div className="ws-start">
                <HeroArt variant="full" />
                <div className="ws-hero-copy">
                  <Chip kind="sim">{t('badge.mock')}</Chip>
                  <h1 className="ws-hero-title">{t('ws.hero.title')}</h1>
                  <p className="ws-hero-sub">{t('ws.hero.sub')}</p>
                </div>
                <div className="ws-start-card" role="menu">{addMenu}</div>
              </div>)
            : !open.length && <div className="ws-none">{t('ws.empty')}</div>}
          {stable.map((w) => {
            const p = place.items[w.id]
            const shown = w.open && (!narrow || w.id === focusId)
            const b = badges[w.id] ?? 0
            return (
              <div key={w.id} className={`ws-win role-${w.role}${w.id === focusId ? ' foc' : ''}${overId === w.id && dragId !== w.id ? ' over' : ''}`}
                style={{ display: shown ? undefined : 'none', ...(narrow || !p ? { inset: GAP / 2 } : { left: `calc(${p.left}% + ${GAP / 2}px)`, top: `calc(${p.top}% + ${GAP / 2}px)`, width: `calc(${p.width}% - ${GAP}px)`, height: `calc(${p.height}% - ${GAP}px)` }) }}
                onDragOver={(e) => { if (dragId) { e.preventDefault(); setOverId(w.id) } }}
                onDrop={(e) => { e.preventDefault(); if (dragId) commit(moveWin(stRef.current, dragId, w.id)); setDragId(null); setOverId(null) }}>
                <div className="ws-stripe" />
                <div className="ws-wh" draggable title={t('ws.drag')} onClick={() => commit(focusWin(stRef.current, w.id))}
                  onDragStart={(e) => { setDragId(w.id); e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', w.id) } catch { /* bỏ qua */ } }}
                  onDragEnd={() => { setDragId(null); setOverId(null) }}>
                  <span className="ws-grip" aria-hidden><Icon name="grip" size={14} /></span>
                  <span className="ws-title"><b>{w.name}</b> <span className="muted">· {t(`role.${w.role}`)}</span>{b > 0 && <span className="ws-pend">{t('ws.pending', { n: b })}</span>}</span>
                  <button className="ws-ib" aria-label={`${t('ws.min')} — ${w.name}`} title={t('ws.min')} onClick={(e) => { e.stopPropagation(); commit(minimizeWin(stRef.current, w.id)) }}><Icon name="minus" size={15} /></button>
                  <button className="ws-ib" aria-label={`${t('ws.close')} — ${w.name}`} title={t('ws.close')} onClick={(e) => { e.stopPropagation(); commit(closeWin(stRef.current, w.id)) }}><Icon name="x" size={15} /></button>
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
          {!narrow && place.splitters.map((sp) => (
            <div key={`${sp.kind}-${sp.row}-${sp.index}`} className={`ws-split ${sp.kind}`} role="separator" tabIndex={0}
              aria-orientation={sp.kind === 'col' ? 'vertical' : 'horizontal'} aria-valuenow={sp.value} aria-valuemin={12} aria-valuemax={88} aria-label={t('ws.resize')} title={t('ws.resize')}
              style={sp.kind === 'col' ? { left: `calc(${sp.left}% - ${GAP / 2}px)`, top: `calc(${sp.top}% + ${GAP / 2}px)`, height: `calc(${sp.height}% - ${GAP}px)`, width: GAP } : { top: `calc(${sp.top}% - ${GAP / 2}px)`, left: GAP / 2, right: GAP / 2, height: GAP }}
              onPointerDown={(e) => startSplit(e, sp)}
              onDoubleClick={() => commit(resetSizes(stRef.current))}
              onKeyDown={(e) => {
                const step = e.key === (sp.kind === 'col' ? 'ArrowRight' : 'ArrowDown') ? 0.03 : e.key === (sp.kind === 'col' ? 'ArrowLeft' : 'ArrowUp') ? -0.03 : 0
                if (step) { e.preventDefault(); commit(dragSplit(stRef.current, width, sp, step)) }
              }} />))}
        </div>
      </section>
    </div>
  )
}
