import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { api, ApiError, getSession, setSession, type Role } from '../api'
import { Chip, ErrorNote } from '../components/ui'
import { Icon } from '../components/Icon'
import { HeroArt } from '../components/HeroArt'
import { Walkthrough, type WalkthroughStep } from '../components/Walkthrough'
import { Brand } from '../components/TopBar'
import { gsap, reducedMotion, useAutoEnter, useGSAP } from '../motion'
import { useI18n } from '../i18n'
import {
  addWin, CHAIN, closeWin, EMPTY, focusWin, MAX_WINS, minimizeWin, insertWin, parse, placement, resetSizes, serialize, dragSplit, TEAM, updateToken,
  winId, WsLimitError, type Splitter, type Win, type WsState,
} from '../workspace'
import { ACCENT_PRESETS, applyAccent, applyTheme, currentAccent, currentTheme, type Theme } from '../theme'
import { LoginForm } from './Login'

const KEY = 'pivot.workspace'
const WINDOW_LAYOUT_KEY = 'pivot.windowLayout'
const GAP = 10 // px giữa các khung (cũng là bề rộng vùng bắt của thanh kéo)
type WindowRect = { x: number; y: number; w: number; h: number; max?: boolean }
const defaultWindowRect = (index: number, total: number): WindowRect => {
  const cols = total <= 2 ? total : Math.ceil(Math.sqrt(total))
  const rows = Math.ceil(total / cols)
  const w = 100 / cols, h = 100 / rows
  return { x: (index % cols) * w + (index % cols ? 1 : 0), y: Math.floor(index / cols) * h + (index ? 1 : 0), w: w - 1, h: h - 1 }
}
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
  const [dropSide, setDropSide] = useState<'left' | 'right' | 'top' | 'bottom' | 'center'>('center')
  const [width, setWidth] = useState(1200)
  const [theme, setThemeState] = useState<Theme>(currentTheme)
  const [accent, setAccentState] = useState(currentAccent)
  const [accentDraft, setAccentDraft] = useState(accent)
  const [appearanceOpen, setAppearanceOpen] = useState(false)
  const [walkthroughOpen, setWalkthroughOpen] = useState(false)
  const [windowRects, setWindowRects] = useState<Record<string, WindowRect>>(() => { try { return JSON.parse(sessionStorage.getItem(WINDOW_LAYOUT_KEY) || '{}') } catch { return {} } })
  const [snapPreview, setSnapPreview] = useState<WindowRect | null>(null)
  const [dockTooltip, setDockTooltip] = useState<{ label: string; x: number; y: number } | null>(null)
  const [snapFlyout, setSnapFlyout] = useState<{ left: number; top: number } | null>(null)
  const snapTimer = useRef<number | null>(null)
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
  const appearanceEl = useRef<HTMLDivElement | null>(null)
  const dockRef = useRef<HTMLElement | null>(null)

  const commit = useCallback((next: WsState) => { stRef.current = next; setSt(next) }, [])
  useEffect(() => { try { sessionStorage.setItem(KEY, serialize(st)) } catch { /* bỏ qua */ } }, [st])
  useEffect(() => {
    setWindowRects((current) => {
      const next = { ...current }
      st.wins.filter((w) => w.open).forEach((w, i, all) => { if (!next[w.id]) next[w.id] = defaultWindowRect(i, all.length) })
      return next
    })
  }, [st.wins])
  useEffect(() => { try { sessionStorage.setItem(WINDOW_LAYOUT_KEY, JSON.stringify(windowRects)) } catch { /* bỏ qua */ } }, [windowRects])
  useEffect(() => {
    const dock = dockRef.current
    if (!dock) return
    let frame = 0, x = 0
    const items = () => [...dock.querySelectorAll<HTMLElement>('.ws-node, .ws-add, .ws-appearance')]
    const move = (e: PointerEvent) => {
      x = e.clientX
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        items().forEach((el) => {
          const center = el.getBoundingClientRect().left + el.offsetWidth / 2
          const influence = Math.max(0, 1 - Math.abs(center - x) / 150)
          el.style.setProperty('--dock-scale', String(1 + influence * 0.28))
        })
      })
    }
    const leave = () => { if (frame) cancelAnimationFrame(frame); frame = 0; items().forEach((el) => el.style.setProperty('--dock-scale', '1')) }
    dock.addEventListener('pointermove', move, { passive: true }); dock.addEventListener('pointerleave', leave)
    return () => { dock.removeEventListener('pointermove', move); dock.removeEventListener('pointerleave', leave); leave() }
  }, [])

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
      if (d.type === 'logection:ready') { sendSession(id); hit[1].contentWindow?.postMessage({ type: 'logection:lang', lang }, location.origin); hit[1].contentWindow?.postMessage({ type: 'logection:theme', theme }, location.origin); hit[1].contentWindow?.postMessage({ type: 'logection:accent', accent }, location.origin) }
      else if (d.type === 'logection:badge') setBadges((b) => (b[id] === d.n ? b : { ...b, [id]: d.n ?? 0 }))
      else if (d.type === 'logection:logout') commit(closeWin(stRef.current, id))
      else if (d.type === 'logection:expired') { const w = stRef.current.wins.find((x) => x.id === id); if (w) void relogin(w) }
    }
    window.addEventListener('message', on)
    return () => window.removeEventListener('message', on)
  }, [commit, relogin, sendSession, lang, theme, accent])

  useEffect(() => { for (const f of frames.current.values()) f.contentWindow?.postMessage({ type: 'logection:lang', lang }, location.origin) }, [lang])
  useEffect(() => { // chế độ sáng/tối: áp dụng cho trang bao ngoài và phát tới mọi cửa sổ nhúng
    applyTheme(theme)
    for (const f of frames.current.values()) f.contentWindow?.postMessage({ type: 'logection:theme', theme }, location.origin)
  }, [theme])
  const setTheme = (th: Theme) => { applyTheme(th, true); setThemeState(th) }
  useEffect(() => {
    applyAccent(accent)
    setAccentDraft(accent)
    for (const f of frames.current.values()) f.contentWindow?.postMessage({ type: 'logection:accent', accent }, location.origin)
  }, [accent])
  const setAccent = (color: string) => {
    if (!/^#[\da-f]{6}$/i.test(color)) return
    applyAccent(color, true)
    setAccentState(color.toLowerCase())
    for (const f of frames.current.values()) f.contentWindow?.postMessage({ type: 'logection:accent', accent: color.toLowerCase() }, location.origin)
  }

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

  useEffect(() => {
    if (!appearanceOpen) return
    const out = (e: MouseEvent) => { if (!appearanceEl.current?.contains(e.target as Node)) setAppearanceOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setAppearanceOpen(false) }
    document.addEventListener('mousedown', out); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', out); document.removeEventListener('keydown', esc) }
  }, [appearanceOpen])

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

  function startWindowAction(e: React.PointerEvent<HTMLElement>, id: string, action: 'move' | 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw') {
    if (e.button !== 0 || (e.target as HTMLElement).closest('button')) return
    const area = gridEl.current
    if (!area) return
    e.preventDefault()
    commit(focusWin(stRef.current, id))
    const bounds = area.getBoundingClientRect()
    const initial = windowRects[id] ?? { x: 2, y: 2, w: 48, h: 48 }
    const sx = e.clientX, sy = e.clientY
    const startRect = { ...initial }
    const winEl = [...area.querySelectorAll<HTMLElement>('.ws-win')].find((el) => el.dataset.windowId === id)
    let dxPx = 0, dyPx = 0
    let hintKey = ''
    const boundedDelta = (clientX: number, clientY: number) => {
      let dx = clientX - sx, dy = clientY - sy
      const minW = Math.min(100, 280 / bounds.width * 100), minH = Math.min(100, 220 / bounds.height * 100)
      if (action === 'move') {
        dx = Math.max(-startRect.x * bounds.width / 100, Math.min((100 - startRect.x - startRect.w) * bounds.width / 100, dx))
        dy = Math.max(-startRect.y * bounds.height / 100, Math.min((100 - startRect.y - startRect.h) * bounds.height / 100, dy))
      } else {
        if (action.includes('e')) dx = Math.max((minW - startRect.w) * bounds.width / 100, Math.min((100 - startRect.x - startRect.w) * bounds.width / 100, dx))
        if (action.includes('w')) dx = Math.max(-startRect.x * bounds.width / 100, Math.min((startRect.w - minW) * bounds.width / 100, dx))
        if (action.includes('s')) dy = Math.max((minH - startRect.h) * bounds.height / 100, Math.min((100 - startRect.y - startRect.h) * bounds.height / 100, dy))
        if (action.includes('n')) dy = Math.max(-startRect.y * bounds.height / 100, Math.min((startRect.h - minH) * bounds.height / 100, dy))
      }
      return { dx, dy }
    }
    const move = (ev: PointerEvent) => {
      ;({ dx: dxPx, dy: dyPx } = boundedDelta(ev.clientX, ev.clientY))
      if (action === 'move') {
        const px = ev.clientX - bounds.left, py = ev.clientY - bounds.top, edge = 28
        let hint: WindowRect | null = null
        if (py < edge && px < edge) hint = { x: 0, y: 0, w: 50, h: 50 }
        else if (py < edge && px > bounds.width - edge) hint = { x: 50, y: 0, w: 50, h: 50 }
        else if (py > bounds.height - edge && px < edge) hint = { x: 0, y: 50, w: 50, h: 50 }
        else if (py > bounds.height - edge && px > bounds.width - edge) hint = { x: 50, y: 50, w: 50, h: 50 }
        else if (px < edge) hint = { x: 0, y: 0, w: 50, h: 100 }
        else if (px > bounds.width - edge) hint = { x: 50, y: 0, w: 50, h: 100 }
        else if (py < edge) hint = { x: 0, y: 0, w: 100, h: 100, max: true }
        const key = hint ? `${hint.x}:${hint.y}:${hint.w}:${hint.h}` : ''
        if (key !== hintKey) { hintKey = key; setSnapPreview(hint) }
      }
      if (!winEl) return
      winEl.classList.add('ws-window-live-drag')
      if (action === 'move') { winEl.style.transform = `translate3d(${dxPx}px, ${dyPx}px, 0)`; return }
      const dx = dxPx / bounds.width * 100, dy = dyPx / bounds.height * 100
      const minW = Math.min(100, 280 / bounds.width * 100), minH = Math.min(100, 220 / bounds.height * 100)
      const nextW = action.includes('e') ? Math.max(minW, Math.min(100 - startRect.x, startRect.w + dx)) : action.includes('w') ? Math.max(minW, startRect.w - dx) : startRect.w
      const nextH = action.includes('s') ? Math.max(minH, Math.min(100 - startRect.y, startRect.h + dy)) : action.includes('n') ? Math.max(minH, startRect.h - dy) : startRect.h
      const scaleX = nextW / startRect.w, scaleY = nextH / startRect.h
      winEl.style.transformOrigin = `${action.includes('w') ? 'right' : 'left'} ${action.includes('n') ? 'bottom' : 'top'}`
      winEl.style.transform = `scale(${scaleX}, ${scaleY})`
    }
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up)
      setSnapPreview(null)
      ;({ dx: dxPx, dy: dyPx } = boundedDelta(ev.clientX, ev.clientY))
      const dx = dxPx / bounds.width * 100, dy = dyPx / bounds.height * 100
      const result = { ...startRect, max: false }
      if (action === 'move') { result.x = Math.min(100 - result.w, Math.max(0, startRect.x + dx)); result.y = Math.min(100 - result.h, Math.max(0, startRect.y + dy)) }
      const minW = Math.min(100, 280 / bounds.width * 100), minH = Math.min(100, 220 / bounds.height * 100)
      if (action.includes('e')) result.w = Math.max(minW, Math.min(100 - startRect.x, startRect.w + dx))
      if (action.includes('s')) result.h = Math.max(minH, Math.min(100 - startRect.y, startRect.h + dy))
      if (action.includes('w')) { const w = Math.max(minW, Math.min(startRect.w - dx, startRect.x + startRect.w)); result.x = startRect.x + startRect.w - w; result.w = w }
      if (action.includes('n')) { const h = Math.max(minH, Math.min(startRect.h - dy, startRect.y + startRect.h)); result.y = startRect.y + startRect.h - h; result.h = h }
      const edgeX = ev.clientX - bounds.left, edgeY = ev.clientY - bounds.top
      if (action === 'move' && edgeY < 18 && edgeX < 18) result.x = 0, result.y = 0, result.w = 50, result.h = 50
      else if (action === 'move' && edgeY < 18 && edgeX > bounds.width - 18) result.x = 50, result.y = 0, result.w = 50, result.h = 50
      else if (action === 'move' && edgeY > bounds.height - 18 && edgeX < 18) result.x = 0, result.y = 50, result.w = 50, result.h = 50
      else if (action === 'move' && edgeY > bounds.height - 18 && edgeX > bounds.width - 18) result.x = 50, result.y = 50, result.w = 50, result.h = 50
      else if (action === 'move' && edgeY < 18) result.x = 0, result.y = 0, result.w = 100, result.h = 100, result.max = true
      else if (action === 'move' && edgeX < 12) result.x = 0, result.y = 0, result.w = 50, result.h = 100
      else if (action === 'move' && edgeX > bounds.width - 12) result.x = 50, result.y = 0, result.w = 50, result.h = 100
      // Clamp after movement, resize and snap so no edge can escape the workspace.
      result.x = Math.max(0, Math.min(100, result.x))
      result.y = Math.max(0, Math.min(100, result.y))
      result.w = Math.max(0, Math.min(result.w, 100 - result.x))
      result.h = Math.max(0, Math.min(result.h, 100 - result.y))
      flushSync(() => setWindowRects((all) => ({ ...all, [id]: result })))
      if (winEl) { winEl.classList.remove('ws-window-live-drag'); winEl.style.transform = ''; winEl.style.transformOrigin = '' }
      setDragId(null)
    }
    setDragId(id)
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up)
  }

  function applySnapLayout(layout: 'columns' | 'three' | 'quarters' | 'main') {
    const ids = stRef.current.wins.filter((w) => w.open).map((w) => w.id)
    const zones: WindowRect[] = layout === 'columns' ? [{ x: 0, y: 0, w: 50, h: 100 }, { x: 50, y: 0, w: 50, h: 100 }]
      : layout === 'three' ? [{ x: 0, y: 0, w: 33.33, h: 100 }, { x: 33.33, y: 0, w: 33.34, h: 100 }, { x: 66.67, y: 0, w: 33.33, h: 100 }]
      : layout === 'quarters' ? [{ x: 0, y: 0, w: 50, h: 50 }, { x: 50, y: 0, w: 50, h: 50 }, { x: 0, y: 50, w: 50, h: 50 }, { x: 50, y: 50, w: 50, h: 50 }]
      : [{ x: 0, y: 0, w: 66, h: 100 }, { x: 66, y: 0, w: 34, h: 50 }, { x: 66, y: 50, w: 34, h: 50 }]
    setWindowRects((all) => {
      const next = { ...all }
      ids.forEach((id, i) => { if (zones[i]) next[id] = zones[i] })
      return next
    })
    setSnapFlyout(null)
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
  // Màn hình hẹp luôn là một cửa sổ toàn vùng; chuyển tài khoản qua dock.
  const narrow = width < 768
  const stable = [...wins].sort((a, b) => (a.id < b.id ? -1 : 1)) // thứ tự DOM cố định (đổi thứ tự DOM sẽ làm khung nhúng tải lại); thứ tự hiển thị dùng CSS `order`
  const focusId = st.focus ?? open[0]?.id
  const showDockTooltip = (e: React.MouseEvent<HTMLElement>, label: string) => { const r = e.currentTarget.getBoundingClientRect(); setDockTooltip({ label, x: r.left + r.width / 2, y: r.top - 12 }) }

  const walkthroughSteps: WalkthroughStep[] = [
    { target: '.ws-bar', title: t('guide.workspace.bar.title'), body: t('guide.workspace.bar.body') },
    { target: '.ws-add', title: t('guide.workspace.add.title'), body: t('guide.workspace.add.body') },
    ...(!wins.length ? [{ target: '.ws-start-card', title: t('guide.workspace.roles.title'), body: t('guide.workspace.roles.body') }] : []),
    ...(open.length ? [
      { target: '.ws-win.foc .ws-wh', title: t('guide.workspace.move.title'), body: t('guide.workspace.move.body') },
      ...(!narrow ? [{ target: '.ws-win.foc .ws-ib[aria-label="Maximize"]', title: t('guide.workspace.snap.title'), body: t(open.length > 1 ? 'guide.workspace.snap.body' : 'guide.workspace.snap.single') }] : []),
      ...(!narrow && place.splitters.length ? [{ target: '.ws-split', title: t('guide.workspace.resize.title'), body: t('guide.workspace.resize.body') }] : []),
      { target: narrow ? '.ws-nodes' : '.ws-dock', title: t('guide.workspace.switch.title'), body: t(narrow ? 'guide.workspace.switch.mobile' : 'guide.workspace.switch.body') },
      { target: '.ws-win.foc .ws-frame', title: t('guide.workspace.app.title'), body: t('guide.workspace.app.body') },
    ] : []),
    { target: '.ws-appearance', title: t('guide.workspace.appearance.title'), body: t('guide.workspace.appearance.body') },
  ]

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
      <nav ref={dockRef} className={`ws-rail${slim ? ' slim' : ''}`} aria-label={t('ws.rail')}>
        <div className="ws-rail-h">
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
              <button key={w.id} data-label={label} onMouseEnter={(e) => showDockTooltip(e, label)} onMouseLeave={() => setDockTooltip(null)} className={`ws-node role-${w.role}${isOpen ? '' : ' bg'}${isOpen && w.id === focusId ? ' foc' : ''}`}
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
          <button className="ws-add" data-label={t('ws.add')} onMouseEnter={(e) => showDockTooltip(e, t('ws.add'))} onMouseLeave={() => setDockTooltip(null)} aria-label={t('ws.add')} title={t('ws.add')} aria-expanded={pop !== 'closed'} aria-haspopup="menu" onClick={() => { setErr(null); setAppearanceOpen(false); setPop(pop === 'closed' ? 'list' : 'closed') }}>
            <Icon name="plus" size={16} />{!slim && <span>{t('ws.add')}</span>}
          </button>
          <div className="ws-appearance-wrap" ref={appearanceEl}>
            <button className="ws-appearance" data-label={t('theme.appearance')} onMouseEnter={(e) => showDockTooltip(e, t('theme.appearance'))} onMouseLeave={() => setDockTooltip(null)} aria-label={t('theme.appearance')} title={t('theme.appearance')} aria-expanded={appearanceOpen} aria-haspopup="dialog"
              onClick={() => { setPop('closed'); setAppearanceOpen((open) => !open) }}>
              <Icon name="palette" size={17} />{!slim && <span>{t('theme.label')}</span>}
            </button>
            {appearanceOpen && (
              <section className="ws-appearance-pop" role="dialog" aria-label={t('theme.appearance')}>
                <h2>{t('theme.appearance')}</h2>
                <div className="ws-appearance-block">
                  <span className="ws-appearance-label">{t('theme.mode')}</span>
                  <div className="ws-mode-options" role="group" aria-label={t('theme.mode')}>
                    {(['light', 'dark'] as const).map((m) => (
                      <button key={m} className={theme === m ? 'on' : ''} aria-pressed={theme === m} onClick={() => setTheme(m)}>
                        <Icon name={m === 'light' ? 'sun' : 'moon'} size={16} /><span>{t(`theme.${m}`)}</span>
                      </button>))}
                  </div>
                </div>
                <div className="ws-appearance-block">
                  <span className="ws-appearance-label">{t('theme.accent')}</span>
                  <div className="ws-color-grid" role="group" aria-label={t('theme.presets')}>
                    {ACCENT_PRESETS.map((color) => (
                      <button key={color} className={`ws-color-swatch${accent.toLowerCase() === color.toLowerCase() ? ' selected' : ''}`}
                        style={{ backgroundColor: color }} aria-label={`${t('theme.accent')} ${color}`} title={color} aria-pressed={accent.toLowerCase() === color.toLowerCase()}
                        onClick={() => setAccent(color)} />))}
                  </div>
                </div>
                <div className="ws-custom-color">
                  <span className="ws-appearance-label">{t('theme.custom')}</span>
                  <label className="ws-color-hex">
                    <span>{t('theme.hex')}</span>
                    <input aria-label={t('theme.hex')} value={accentDraft.toUpperCase()} maxLength={7}
                      onChange={(e) => setAccentDraft(e.target.value)}
                      onBlur={() => /^#[\da-f]{6}$/i.test(accentDraft) ? setAccent(accentDraft) : setAccentDraft(accent)}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.currentTarget.blur() } }} />
                  </label>
                  <label className="ws-color-picker" title={t('theme.colorPicker')}>
                    <input type="color" aria-label={t('theme.colorPicker')} value={accent} onChange={(e) => setAccent(e.target.value)} />
                    <span>{t('theme.colorPicker')}</span>
                  </label>
                </div>
              </section>)}
          </div>
          {wins.length > 0 && pop !== 'closed' && (
            <div className="ws-pop" role="menu">
              {addMenu}
            </div>)}
        </div>
      </nav>
      {dockTooltip && <div className="ws-dock-tooltip" style={{ left: dockTooltip.x, top: dockTooltip.y }} role="tooltip">{dockTooltip.label}</div>}

      <section className="ws-work">
        <div className="ws-bar">
          <button className="brand-btn ws-top-brand" aria-label="LOGECTION" onClick={onHome}><Brand /></button>
          <div className="seg" role="group" aria-label="Language">
            {(['vi', 'en'] as const).map((l) => <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
          </div>
          <button className="btn sm icon" aria-label={t('guide.open')} title={t('guide.open')} onClick={() => setWalkthroughOpen(true)}><Icon name="help" size={16} /></button>
          <span className="muted">{t('ws.count', { n: open.length })}{wins.length > open.length ? ` · ${t('ws.bgN', { n: wins.length - open.length })}` : ''}</span>
          <span className="grow" />
          {st.sizes && <button className="btn sm" onClick={() => commit(resetSizes(stRef.current))}>{t('ws.even')}</button>}
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
          {snapPreview && <div className="ws-snap-preview" style={{ left: `${snapPreview.x}%`, top: `${snapPreview.y}%`, width: `${snapPreview.w}%`, height: `${snapPreview.h}%` }} aria-hidden />}
          {snapFlyout && <div className="ws-snap-flyout" style={snapFlyout} onMouseEnter={() => { if (snapTimer.current) window.clearTimeout(snapTimer.current) }} onMouseLeave={() => setSnapFlyout(null)}>
            <button onClick={() => applySnapLayout('columns')} aria-label="Two columns"><i className="snap-mini two"><b /><b /></i></button>
            <button onClick={() => applySnapLayout('three')} aria-label="Three columns"><i className="snap-mini three"><b /><b /><b /></i></button>
            <button onClick={() => applySnapLayout('quarters')} aria-label="Four corners"><i className="snap-mini four"><b /><b /><b /><b /></i></button>
            <button onClick={() => applySnapLayout('main')} aria-label="Large area and two small areas"><i className="snap-mini main"><b /><b /><b /></i></button>
          </div>}
          {stable.map((w) => {
            const rect = windowRects[w.id] ?? defaultWindowRect(Math.max(0, open.findIndex((x) => x.id === w.id)), Math.max(1, open.length))
            const shown = w.open && (!narrow || w.id === focusId)
            const b = badges[w.id] ?? 0
            return (
              <div key={w.id} data-window-id={w.id} className={`ws-win role-${w.role}${w.id === focusId ? ' foc' : ''}${overId === w.id && dragId !== w.id ? ` over drop-${dropSide}` : ''}${rect.max ? ' maximized' : ''}`}
                style={{ display: shown ? undefined : 'none', ...(narrow ? { inset: 0, width: '100%', height: '100%', zIndex: w.id === focusId ? 100 : 1 } : { left: `${rect.x}%`, top: `${rect.y}%`, width: `${rect.w}%`, height: `${rect.h}%`, zIndex: w.id === focusId ? 100 : Math.max(1, open.findIndex((x) => x.id === w.id) + 1) }) }}
                onPointerDown={() => { if (stRef.current.focus !== w.id) commit(focusWin(stRef.current, w.id)) }}
                onDragOver={(e) => { if (dragId && dragId !== w.id) { e.preventDefault(); setOverId(w.id); const r = e.currentTarget.getBoundingClientRect(); const x = (e.clientX-r.left)/r.width, y = (e.clientY-r.top)/r.height; const edge = Math.min(x,1-x,y,1-y); setDropSide(edge > .28 ? 'center' : edge === x ? 'left' : edge === 1-x ? 'right' : edge === y ? 'top' : 'bottom') } }}
                onDrop={(e) => { e.preventDefault(); if (dragId) commit(insertWin(stRef.current, dragId, w.id, dropSide)); setDragId(null); setOverId(null) }}>
                <div className="ws-stripe" />
                {!narrow && ['n','s','e','w','ne','nw','se','sw'].map((edge) => <div key={edge} className={`ws-resize ws-resize-${edge}`} onPointerDown={(e) => startWindowAction(e, w.id, edge as 'n'|'s'|'e'|'w'|'ne'|'nw'|'se'|'sw')} />)}
                <div className="ws-wh" title={t('ws.drag')} onPointerDown={(e) => startWindowAction(e, w.id, 'move')}>
                  <span className="ws-grip" aria-hidden><Icon name="grip" size={14} /></span>
                  <span className="ws-title"><b>{w.name}</b> <span className="muted">· {t(`role.${w.role}`)}</span>{b > 0 && <span className="ws-pend">{t('ws.pending', { n: b })}</span>}</span>
                  <button className="ws-ib" aria-label="Maximize" title="Maximize" onMouseEnter={(e) => { if (snapTimer.current) window.clearTimeout(snapTimer.current); const grid = gridEl.current?.getBoundingClientRect(), button = e.currentTarget.getBoundingClientRect(); if (!grid) return; const width = 184, height = 148; const left = Math.max(8, Math.min(button.left - grid.left - width / 2, grid.width - width - 8)); const top = Math.max(8, Math.min(button.bottom - grid.top + 8, grid.height - height - 8)); snapTimer.current = window.setTimeout(() => setSnapFlyout({ left, top }), 450) }} onMouseLeave={() => { if (snapTimer.current) window.clearTimeout(snapTimer.current); snapTimer.current = window.setTimeout(() => setSnapFlyout(null), 450) }} onClick={(e) => { e.stopPropagation(); const r = windowRects[w.id] ?? rect; setWindowRects((all) => ({ ...all, [w.id]: r.max ? { ...r, x: 2, y: 2, w: 48, h: 48, max: false } : { x: 0, y: 0, w: 100, h: 100, max: true } })) }}>□</button>
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
        {!!wins.length && <div className="ws-dock" aria-label={t('ws.people')}>
          {wins.map((w) => <button key={w.id} className={`ws-dock-item${w.id === focusId ? ' active' : ''}`} title={`${w.name} · ${t(`role.${w.role}`)}`} onClick={() => commit(focusWin(stRef.current, w.id))}>
            <span className={`ws-dock-avatar role-${w.role}`}>{initials(w.name)}</span><i className={w.open ? 'running' : ''} />
          </button>)}<span className="ws-dock-divider" /><button className="ws-dock-item ws-dock-add" aria-label={t('ws.add')} title={t('ws.add')} onClick={() => { setErr(null); setPop(pop === 'closed' ? 'list' : 'closed') }}><span className="ws-dock-avatar">+</span></button>
        </div>}
      </section>
      <Walkthrough steps={walkthroughSteps} open={walkthroughOpen} onClose={() => setWalkthroughOpen(false)} />
    </div>
  )
}
