import { useEffect, useRef, useState } from 'react'
import { useData } from '../useData'
import { api, ApiError, getAdminKey } from '../api'
import { ageMinutes } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { Chip, Hint } from './ui'
import { Icon } from './Icon'

export function Brand() {
  return <div className="brand"><div className="logo" aria-hidden>L</div><b>LOGECTION</b></div>
}

const SEV_ORDER = ['critical', 'high', 'medium', 'low'] as const

function Bell() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const list = useData(() => api.notifications(), 4000)
  useEffect(() => {
    if (!open) return
    const out = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', out)
    return () => document.removeEventListener('mousedown', out)
  }, [open])
  const items = (list.data?.items ?? []).filter((n) => n.channel === 'in_app').slice(0, 15)
  const unread = list.data?.unread ?? 0
  const topUnread = SEV_ORDER.find((s) => items.some((n) => !n.read && n.payload.severity === s)) // màu chấm số = mức cao nhất chưa đọc
  return (
    <div className="menu-wrap" ref={wrap}>
      <button className={`bell${topUnread ? ` sev-${topUnread}` : ''}`} aria-label={unread > 0 ? `${t('bell.title')}: ${unread}` : t('bell.title')} aria-expanded={open} onClick={() => setOpen((v) => !v)}><Icon name="bell" size={18} />{unread > 0 && <span className="dot" aria-hidden>{unread > 9 ? '9+' : unread}</span>}</button>
      {open && (
        <div className="menu bell-list" role="menu">
          {!items.length && <div className="muted small" style={{ padding: 10 }}>{t('bell.empty')}</div>}
          {items.map((n) => (
            <button key={n.id} role="menuitem" className={`it sev-${n.payload.severity}${n.read ? '' : ' unread'}`} onClick={() => { setOpen(false); window.location.hash = '#/exceptions' }}>
              <span className="row"><Chip kind={`sev-${n.payload.severity}`}>{t(`ex.sev.${n.payload.severity}`)}</Chip><b>{t(`ex.cat.${n.payload.category}`)}</b></span>
              <span className="muted small">{n.payload.shipment_code} · {n.payload.plate}{n.payload.escalated ? ` · ${t('ex.escalated')}` : ''}</span>
            </button>))}
          {unread > 0 && <button role="menuitem" onClick={() => { void api.readNotifications().then(() => list.reload(true)) }}>{t('bell.read')}</button>}
        </div>)}
    </div>
  )
}

/** Nhà vận tải: nhắc ngay ở thanh đầu khi có xe quá hạn vị trí; bấm để gửi vị trí cả các xe đó (không cần mở bảng xe). */
function StaleFleet() {
  const { t } = useI18n()
  const { me, meta } = useApp()
  const vehicles = useData(() => api.vehicles(), 15000)
  const [busy, setBusy] = useState(false)
  const limit = meta?.stale_position_minutes ?? 5
  const stale = (vehicles.data ?? []).filter((v) => v.tenant_id === me?.org_id && v.status !== 'offline' && (() => { const a = ageMinutes(v.position_updated_at); return a == null || a > limit })())
  if (!stale.length) return null
  async function fix() {
    setBusy(true)
    try { for (const v of stale) await api.sendVehicleEvent(v.id, 'VEHICLE_POSITION'); await new Promise((r) => setTimeout(r, 1600)); await vehicles.reload(true) }
    catch { /* lỗi mạng/quyền: nút bật lại để thử tiếp, không để lỗi thoát ra thành "unhandled rejection" */ }
    finally { setBusy(false) }
  }
  return (
    <button className="stale-chip" disabled={busy} title={t('bar.staleTip')} onClick={fix}>
      {t('bar.stale', { n: stale.length, m: limit })} · <b>{t('bar.staleFix')}</b>
    </button>
  )
}

export function TopBar() {
  const { t, lang, setLang } = useI18n()
  const { me, meta, logout, bump } = useApp()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => { // đóng menu khi bấm ra ngoài hoặc nhấn Escape
    if (!open) return
    const out = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', out); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', out); document.removeEventListener('keydown', esc) }
  }, [open])

  async function retime() {
    setOpen(false); setBusy(true)
    try { await api.retime(); setMsg(t('menu.retimeDone')); bump() }
    catch (e) { setMsg(e instanceof ApiError ? e.message : String(e)) }
    finally { setBusy(false); setTimeout(() => setMsg(null), 3500) }
  }

  const sim = meta ? meta.data_mode === 'mock' || meta.is_simulated : true
  const dispatcher = me?.role === 'dispatcher'
  const needKey = !!meta?.admin_key_required && !getAdminKey()
  return (
    <header className="topbar">
      <div className="topbar-in">
        <Brand />
        <div className="ctrl">
          <Chip kind={sim ? 'sim' : 'good'}>● {sim ? t('badge.mock') : t('badge.live')}</Chip>
          {sim && <Hint text={t('badge.mockTip')} />}
        </div>
        {me?.role === 'carrier' && <StaleFleet />}
        {me && <Bell />}
        {me && (
          <div className="menu-wrap" ref={wrap}>
            <button className="who" aria-haspopup="menu" aria-expanded={open} aria-label={t('menu.open')} onClick={() => setOpen((v) => !v)}>
              <span className="avatar" aria-hidden>{me.user_name.slice(0, 1).toUpperCase()}</span>
              <span><b>{me.user_name}</b><small>{t(`role.${me.role}`)}</small></span>
            </button>
            {open && (
              <div className="menu" role="menu">
                <div className="menu-row"><span className="muted small">{t('menu.lang')}</span>
                  <div className="seg" role="group" aria-label={t('menu.lang')}>
                    {(['vi', 'en'] as const).map((l) => <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
                  </div>
                </div>
                {dispatcher && <button role="menuitem" onClick={retime} disabled={busy || needKey} title={needKey ? t('menu.needKey') : undefined}>{t('menu.retime')}</button>}
                {dispatcher && <button role="menuitem" onClick={() => { setOpen(false); window.location.hash = '#/demo' }}>{t('menu.demo')}</button>}
                <button role="menuitem" onClick={logout}>{t('menu.logout')}</button>
              </div>)}
          </div>)}
      </div>
      {msg && <div className="topbar-in"><span className="small muted" role="status">{msg}</span></div>}
    </header>
  )
}
