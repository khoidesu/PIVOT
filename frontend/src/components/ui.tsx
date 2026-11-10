import type { ReactNode } from 'react'
import { ApiError } from '../api'
import { reasonText, useI18n } from '../i18n'
import { fmtTime } from '../fmt'

export const Chip = ({ kind, children, title }: { kind?: string; children: ReactNode; title?: string }) => (
  <span className={`chip ${kind ?? ''}`} title={title}>{children}</span>
)

export function Note({ kind = 'info', children }: { kind?: 'ok' | 'err' | 'warn' | 'info'; children: ReactNode }) {
  return <div className={`note ${kind}`} role={kind === 'err' ? 'alert' : 'status'}>{children}</div>
}

/** Thông báo lỗi API: dùng mã lỗi (code) để ra văn bản đã dịch; kèm lý do re-check nếu có. */
export function ErrorNote({ error }: { error: ApiError }) {
  const { t } = useI18n()
  let text: string
  if (error.code === 'NETWORK') text = t('err.network', { url: import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000' })
  else if (error.code === 'VALIDATION') text = t('err.VALIDATION', { msg: error.message })
  else {
    const key = `err.${error.code}`
    text = t(key) === key ? (error.status === 403 ? t('err.forbidden') : error.message || t('err.generic')) : t(key)
  }
  return (
    <Note kind="err">
      {text}
      {error.reasons.length > 0 && (
        <ul>{error.reasons.map((r, i) => <li key={i}><span className="code">{r.reason_code}</span> — {reasonText(r, t, fmtTime)}</li>)}</ul>
      )}
    </Note>
  )
}

export const Loading = () => { const { t } = useI18n(); return <div className="empty">{t('common.loading')}</div> }

const FLOW = ['proposed', 'pending_acceptance', 'confirmed', 'executing', 'completed']

export function Stepper({ status }: { status: string }) {
  const { t } = useI18n()
  const idx = FLOW.indexOf(status)
  if (idx < 0) return <Chip kind="bad">{t(`ps.${status}`)}</Chip>
  return (
    <div className="stepper" aria-label={t('cf.step')}>
      {FLOW.map((s, i) => (
        <span key={s} className={`step ${i < idx ? 'done' : i === idx ? 'cur' : ''}`} aria-current={i === idx ? 'step' : undefined}>
          <i />{t(`ps.${s}`)}
        </span>
      ))}
    </div>
  )
}

export const loadPct = (kg: number | null, cap: number) => (kg == null ? null : Math.round((kg / cap) * 100))
