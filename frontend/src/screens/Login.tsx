import { useState, type FormEvent } from 'react'
import { ApiError, ROLES, type Role } from '../api'
import { Chip, ErrorNote, Note } from '../components/ui'
import { useI18n } from '../i18n'
import { useApp } from '../store'

// gợi ý điền nhanh (tên của nhóm); người dùng vẫn tự đặt tên tuỳ ý
const QUICK: { name: string; role: Role }[] = [
  { name: 'Nguyên', role: 'shipper' }, { name: 'Minh', role: 'carrier' }, { name: 'Khôi', role: 'node_operator' }, { name: 'Phú', role: 'dispatcher' },
]

export function Login() {
  const { t, lang, setLang } = useI18n()
  const { login, notice } = useApp()
  const [name, setName] = useState('')
  const [role, setRole] = useState<Role>('shipper')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [localErr, setLocalErr] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null); setLocalErr(null)
    const n = name.trim()
    if (n.length < 2) { setLocalErr(t('login.nameRequired')); return }
    setBusy(true)
    try { await login(n, role) }
    catch (err) { setError(err instanceof ApiError ? err : new ApiError(0, 'UNKNOWN', String(err))) }
    finally { setBusy(false) }
  }

  return (
    <main className="login">
      <div className="login-top">
        <div className="brand"><div className="logo" aria-hidden>P</div><div><b>PIVOT</b><span>{t('app.tagline')}</span></div></div>
        <div className="row">
          <Chip kind="sim">● {t('badge.mock')}</Chip>
          <div className="seg" role="group" aria-label={t('topbar.lang')}>
            {(['vi', 'en'] as const).map((l) => <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
          </div>
        </div>
      </div>
      <form className="card login-card stack" onSubmit={submit} aria-label={t('login.title')}>
        <div><h1>{t('login.title')}</h1><span className="muted">{t('login.sub')}</span></div>
        {notice === 'expired' && <Note kind="warn">{t('login.expired')}</Note>}
        <label>{t('login.name')}
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('login.namePh')} maxLength={40} autoFocus autoComplete="off" />
        </label>
        <div className="row small muted">{t('login.quick')}
          {QUICK.map((q) => <button key={q.name} type="button" className="btn sm" onClick={() => { setName(q.name); setRole(q.role) }}>{q.name}</button>)}
        </div>
        <fieldset className="roles">
          <legend>{t('login.role')}</legend>
          {ROLES.map((r) => (
            <label key={r} className={`role-card ${role === r ? 'on' : ''}`}>
              <input type="radio" name="role" value={r} checked={role === r} onChange={() => setRole(r)} />
              <span><b>{t(`role.${r}`)}</b><small>{t(`rd.${r}`)}</small></span>
            </label>))}
        </fieldset>
        {localErr && <Note kind="err">{localErr}</Note>}
        {error && <ErrorNote error={error} />}
        <button className="btn primary" type="submit" disabled={busy}>{busy ? t('login.entering') : t('login.submit')}</button>
        <Note kind="info">{t('login.tabNote')}<br />{t('login.sameNote')}</Note>
      </form>
    </main>
  )
}
