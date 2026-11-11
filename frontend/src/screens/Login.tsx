import { useState, type FormEvent } from 'react'
import { ApiError, ROLES, type Role } from '../api'
import { ErrorNote, Hint, Note } from '../components/ui'
import { useI18n } from '../i18n'

/** Biểu mẫu tên + vai trò (không mật khẩu, chỉ cho dữ liệu mô phỏng). `compact` = dạng gọn trong ngăn "Thêm người". */
export function LoginForm({ onLogin, compact = false }: { onLogin: (name: string, role: Role) => Promise<void>; compact?: boolean }) {
  const { t } = useI18n()
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
    try { await onLogin(n, role); setName('') }
    catch (err) { setError(err instanceof ApiError ? err : new ApiError(0, 'UNKNOWN', String(err))) }
    finally { setBusy(false) }
  }

  const fields = (
    <>
      <label>{t('login.name')}
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('login.namePh')} maxLength={40} autoFocus autoComplete="off" />
      </label>
      {compact ? (
        <label>{t('login.role')}
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>{ROLES.map((r) => <option key={r} value={r}>{t(`role.${r}`)}</option>)}</select>
        </label>
      ) : (
        <fieldset className="roles">
          <legend>{t('login.role')}</legend>
          {ROLES.map((r) => (
            <label key={r} className={`role-card ${role === r ? 'on' : ''}`} title={t(`rd.${r}`)}>
              <input type="radio" name="role" value={r} checked={role === r} onChange={() => setRole(r)} />
              <span><b>{t(`role.${r}`)}</b><small>{t(`rd.${r}`)}</small></span>
            </label>))}
        </fieldset>
      )}
      {localErr && <Note kind="err">{localErr}</Note>}
      {error && <ErrorNote error={error} />}
      <button className="btn primary" type="submit" disabled={busy}>{busy ? t('login.entering') : t('login.submit')}</button>
    </>
  )
  return compact
    ? <form className="stack ws-form" onSubmit={submit} aria-label={t('ws.other')}>{fields}</form>
    : <form className="card login-card stack" onSubmit={submit} aria-label={t('login.title')}><h1>{t('login.title')} <Hint text={t('login.tip')} /></h1>{fields}</form>
}
