import { useEffect, useRef, useState } from 'react'
import { api, ApiError, getAdminKey } from '../api'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { Chip, Hint } from './ui'

export function Brand() {
  return <div className="brand"><div className="logo" aria-hidden>L</div><b>LOGECTION</b></div>
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
