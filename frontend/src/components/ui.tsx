import type { ReactNode } from 'react'
import { ApiError } from '../api'
import { reasonText, useI18n, tCode } from '../i18n'
import { fmtTime } from '../fmt'
import { isConnError } from '../conn'

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

/** Trạng thái lỗi của một truy vấn `useData` (QA-07), dùng chung cho mọi màn:
 *  mất kết nối + còn dữ liệu cũ → cảnh báo "Dữ liệu cũ · mất kết nối"; chưa có dữ liệu → lỗi kết nối; lỗi khác → ErrorNote. */
export function QueryNote({ q }: { q: { error: ApiError | null; data: unknown } }) {
  const { t } = useI18n()
  if (!q.error) return null
  if (q.data != null && isConnError(q.error)) return <Note kind="warn">{t('conn.stale')}</Note>
  return <ErrorNote error={q.error} />
}

export const Loading = () => { const { t } = useI18n(); return <div className="empty">{t('common.loading')}</div> }

const FLOW = ['proposed', 'pending_acceptance', 'confirmed', 'executing', 'completed']

/** Tiến trình gọn: chấm tròn + nhãn của bước hiện tại. */
export function Stepper({ status }: { status: string }) {
  const { t } = useI18n()
  const idx = FLOW.indexOf(status)
  if (idx < 0) return <Chip kind="bad">{tCode(t, 'ps.', status)}</Chip>
  return (
    <span className="dots" role="img" aria-label={`${tCode(t, 'ps.', status)} (${idx + 1}/${FLOW.length})`}>
      <span aria-hidden>{FLOW.map((s, i) => <i key={s} className={i < idx ? 'done' : i === idx ? 'cur' : ''} />)}</span>
      <b>{tCode(t, 'ps.', status)}</b>
    </span>
  )
}

/** Giải thích ngắn khi rê chuột / focus bàn phím (không chiếm chỗ trên màn hình). */
export const Hint = ({ text }: { text: string }) => <span className="hint" tabIndex={0} data-tip={text} aria-label={text}>?</span>

/** Thông tin kỹ thuật/chi tiết: thu gọn mặc định (vẫn truy cập được, bàn phím mở bằng Enter/Space). */
export function More({ label, open, children }: { label?: string; open?: boolean; children: ReactNode }) {
  const { t } = useI18n()
  return <details className="more" open={open}><summary>{label ?? t('more')}</summary><div className="more-body">{children}</div></details>
}

