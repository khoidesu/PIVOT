import { useState, type FormEvent } from 'react'
import { ApiError, ROLES, type Role } from '../api'
import { Brand } from '../components/TopBar'
import { Chip, ErrorNote, Hint, Note } from '../components/ui'
import { useI18n } from '../i18n'
import { useApp } from '../store'

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
        <Brand />
        <div className="row">
          <Chip kind="sim">● {t('badge.mock')}</Chip>
          <div className="seg" role="group" aria-label="Language">
            {(['vi', 'en'] as const).map((l) => <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
          </div>
        </div>
      </div>
      <form className="card login-card stack" onSubmit={submit} aria-label={t('login.title')}>
        <h1>{t('login.title')} <Hint text={t('login.tip')} /></h1>
        {notice === 'expired' && <Note kind="warn">{t('login.expired')}</Note>}
        <label>{t('login.name')}
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('login.namePh')} maxLength={40} autoFocus autoComplete="off" />
        </label>
        <fieldset className="roles">
          <legend>{t('login.role')}</legend>
          {ROLES.map((r) => (
            <label key={r} className={`role-card ${role === r ? 'on' : ''}`} title={t(`rd.${r}`)}>
              <input type="radio" name="role" value={r} checked={role === r} onChange={() => setRole(r)} />
              <span><b>{t(`role.${r}`)}</b><small>{t(`rd.${r}`)}</small></span>
            </label>))}
        </fieldset>
        {localErr && <Note kind="err">{localErr}</Note>}
        {error && <ErrorNote error={error} />}
        <button className="btn primary" type="submit" disabled={busy}>{busy ? t('login.entering') : t('login.submit')}</button>
      </form>
    </main>
  )
}
