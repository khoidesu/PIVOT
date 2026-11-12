import { useMemo, useState } from 'react'
import { api, ApiError, type ExceptionItem } from '../api'
import { Chip, ErrorNote, Hint, Loading, Note } from '../components/ui'
import { fmtTime, nowMs } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const SEV_RANK = { critical: 0, high: 1, medium: 2, low: 3 }
const SEV_KIND = { critical: 'sev-critical', high: 'sev-high', medium: 'sev-medium', low: 'sev-low' } as const
const KINDS: Record<string, string[]> = {
  carrier: ['BREAKDOWN', 'TRAFFIC_INCIDENT', 'CARGO_DAMAGE'], node_operator: ['CARGO_DAMAGE'], shipper: ['CARGO_DAMAGE'], dispatcher: [],
}

export function Exceptions({ go }: { go: (to: string) => void }) {
  const { t } = useI18n()
  const { me } = useApp()
  const exs = useData(() => api.exceptions(), 2500)
  const props = useData(() => api.proposals(), 5000)
  const [onlyOpen, setOnlyOpen] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [pid, setPid] = useState('')
  const [kind, setKind] = useState('')
  const [note, setNote] = useState('')

  const list = useMemo(() => (exs.data ?? []).filter((e) => !onlyOpen || e.status === 'open')
    .sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity] || a.created_at.localeCompare(b.created_at)), [exs.data, onlyOpen])
  const trips = (props.data ?? []).filter((p) => ['confirmed', 'executing'].includes(p.status))
  const kinds = KINDS[me?.role ?? ''] ?? []
  const guard = async (key: string, fn: () => Promise<void>) => {
    setBusy(key); setError(null); setMsg(null)
    try { await fn(); await exs.reload(true) } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) } finally { setBusy(null) }
  }
  const report = () => guard('report', async () => {
    const k = kind || kinds[0]
    await (k === 'CARGO_DAMAGE' ? api.sendEvent(pid || trips[0].id, 'CARGO_DAMAGE_REPORTED', { note: note || null })
      : api.sendEvent(pid || trips[0].id, 'INCIDENT_REPORTED', { kind: k, delay_minutes: k === 'TRAFFIC_INCIDENT' ? 30 : 0, note: note || null }))
    setNote(''); setTimeout(() => { void exs.reload(true) }, 1800)
  })
  const resolve = (e: ExceptionItem, r: 'accept_delay' | 'request_replan') => guard(e.id + r, async () => { await api.resolve(e.id, r) })
  const replan = (e: ExceptionItem) => guard(e.id + 'rp', async () => {
    const r = await api.replan({ id: e.proposal_id, version: e.proposal_version })
    setMsg(t('ex.replanDone', { n: r.new_proposals }))
    go(`/recommend?lot=${r.shipment_id}`)
  })
  const dueText = (e: ExceptionItem) => {
    if (!e.sla_due_at) return ''
    const mins = Math.round((new Date(e.sla_due_at).getTime() - nowMs()) / 60000)
    return mins >= 0 ? `${mins}′` : fmtTime(e.sla_due_at)
  }

  if (exs.loading && !exs.data) return <Loading />
  return (
    <section className="stack">
      <div className="card stack">
        <div className="card-h"><h1>{t('ex.title')}</h1><Chip kind="sim">{t('badge.mock')}</Chip><Hint text={t('ex.simNote')} />
          <div className="seg" role="group" aria-label={t('ex.title')}>
            <button aria-pressed={onlyOpen} onClick={() => setOnlyOpen(true)}>{t('ex.open')}</button>
            <button aria-pressed={!onlyOpen} onClick={() => setOnlyOpen(false)}>{t('ex.all')}</button>
          </div>
        </div>
        {exs.error && <ErrorNote error={exs.error} />}
        {error && <ErrorNote error={error} />}
        {msg && <Note kind="ok">{msg}</Note>}
        {kinds.length > 0 && trips.length > 0 && (
          <div className="row">
            <select aria-label={t('ex.trip')} value={pid || trips[0].id} onChange={(e) => setPid(e.target.value)}>
              {trips.map((p) => <option key={p.id} value={p.id}>{p.shipment.code} · {p.vehicle.plate}</option>)}
            </select>
            <select aria-label={t('ex.report')} value={kind || kinds[0]} onChange={(e) => setKind(e.target.value)}>
              {kinds.map((k) => <option key={k} value={k}>{t(`ex.kind.${k}`)}</option>)}
            </select>
            <input value={note} maxLength={300} placeholder={t('ex.note')} onChange={(e) => setNote(e.target.value)} />
            <button className="btn sm" disabled={!!busy} onClick={report}>{t('ex.report')} · {t('ex.send')}</button>
          </div>)}
      </div>
      {!list.length && <div className="card empty">{t('ex.empty')}</div>}
      {list.map((e) => (
        <article key={e.id} className={`card stack ex ${e.severity}`}>
          <div className="row">
            <Chip kind={SEV_KIND[e.severity]}>{t(`ex.sev.${e.severity}`)}</Chip>
            <b>{t(`ex.cat.${e.exc_type}`)}</b>
            <span className="muted small">{e.shipment_code} · {e.plate}</span>
            {e.status === 'open' && e.sla_due_at && <Chip kind={e.overdue ? 'bad' : ''}>{e.overdue ? t('ex.overdue') : t('ex.sla', { t: dueText(e) })}</Chip>}
            {e.escalated_at && <Chip kind="warn">{t('ex.escalated')}</Chip>}
            {e.status === 'resolved' && <Chip kind="good">✓ {t(`tl.resolve.${e.detail.resolution ?? 'accept_delay'}`)}</Chip>}
          </div>
          {e.detail.note && <div className="muted small">“{e.detail.note}”</div>}
          <ol className="steps">
            {e.tasks.map((k) => (
              <li key={k.id} className={k.status === 'done' ? 'done' : ''}>
                <span>{k.status === 'done' ? '✓' : '○'} {t(`ex.step.${k.step_key}`)}</span>
                <span className="muted small">{t(`ex.owner.${k.owner}`)}</span>
                {k.can_complete && <button className="btn sm" disabled={!!busy} onClick={() => guard(k.id, async () => { await api.completeTask(e.id, k.id) })}>{t('ex.done')}</button>}
              </li>))}
          </ol>
          {e.status === 'open' && (e.can_replan || ['shipper', 'carrier'].includes(me?.role ?? '')) && (
            <div className="row">
              {['shipper', 'carrier'].includes(me?.role ?? '') && <button className="btn sm primary" disabled={!!busy} onClick={() => resolve(e, 'accept_delay')}>{t('tl.resolve.accept_delay')}</button>}
              {e.can_replan && <button className="btn sm" disabled={!!busy} onClick={() => replan(e)}>{t('ex.replan')}</button>}
            </div>)}
        </article>))}
    </section>
  )
}
