import { useEffect, useState } from 'react'
import { api, ApiError, getAdminKey } from '../api'
import { useI18n } from '../i18n'
import { fmtClock, nowMs } from '../fmt'
import { useApp } from '../store'
import { Chip } from './ui'

export function TopBar() {
  const { t, lang, setLang } = useI18n()
  const { me, meta, logout, bump, syncClock } = useApp()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [, tick] = useState(0)
  useEffect(() => { const id = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(id) }, []) // đồng hồ chạy mỗi giây
  useEffect(() => { const id = setInterval(syncClock, 30_000); return () => clearInterval(id) }, [syncClock]) // đồng bộ lại giờ máy chủ mỗi 30 giây

  async function retime() {
    setBusy(true)
    try { await api.retime(); setMsg(t('topbar.retimeDone')); bump() }
    catch (e) { setMsg(e instanceof ApiError ? e.message : String(e)) }
    finally { setBusy(false); setTimeout(() => setMsg(null), 4000) }
  }

  const sim = meta ? meta.data_mode === 'mock' || meta.is_simulated : true
  return (
    <>
      <header className="topbar">
        <div className="topbar-in">
          <div className="brand">
            <div className="logo" aria-hidden>P</div>
            <div><b>PIVOT</b><span>{t('app.tagline')}</span></div>
          </div>
          <div className="ctrl">
            <Chip kind={sim ? 'sim' : 'good'}>● {sim ? t('badge.mock') : t('badge.live')}</Chip>
            {meta && <span className="small">{t('topbar.dataAge', { age: fmtClock(new Date(nowMs()).toISOString()) })}</span>}
          </div>
          {me && (
            <div className="who" aria-label={t('topbar.role')}>
              <b>{me.user_name}</b><span className="muted small"> — {t(`role.${me.role}`)}{me.org_name.startsWith(`${me.user_name} ·`) ? '' : ` · ${me.org_name}`}</span>
            </div>)}
          <div className="seg" role="group" aria-label={t('topbar.lang')}>
            {(['vi', 'en'] as const).map((l) => (
              <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>
            ))}
          </div>
          <button className="btn sm" onClick={logout}>{t('topbar.logout')}</button>
          {me?.role === 'dispatcher' && (
            <button className="btn sm" onClick={retime} disabled={busy || (!!meta?.admin_key_required && !getAdminKey())} title={meta?.admin_key_required && !getAdminKey() ? t('topbar.retimeNeedKey') : undefined}>{t('topbar.retime')}</button>
          )}
        </div>
        {msg && <div className="topbar-in"><span className="small muted" role="status">{msg}</span></div>}
      </header>
    </>
  )
}
