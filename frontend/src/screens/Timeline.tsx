import { useEffect, useState } from 'react'
import { api, ApiError, type ExceptionItem, type Replay } from '../api'
import { Chip, ErrorNote, Loading, More, Note, Stepper } from '../components/ui'
import { fmtClock } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const KIND_ICON: Record<string, string> = { match: '◎', decision: '✔', event: '⇄', exception: '⚠', benefit: '₫' }
const KIND_COLOR: Record<string, string> = { match: 'teal', decision: 'good', event: '', exception: 'warn', benefit: 'good' }
const ABNORMAL = new Set(['late', 'invalid', 'unsupported'])
const PARTY_ROLES = new Set(['shipper', 'carrier'])

export function Timeline({ query }: { query: URLSearchParams }) {
  const { t } = useI18n()
  const { me } = useApp()
  const props = useData(() => api.proposals(), 4000)
  const [pid, setPid] = useState(query.get('p') ?? '')
  const list = props.data ?? []
  useEffect(() => {
    if (!pid && list.length) {
      const pick = list.find((p) => ['executing', 'completed', 'confirmed', 'pending_acceptance'].includes(p.status)) ?? list[0]
      setPid(pick.id)
    }
  }, [list.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const tl = useData(() => (pid ? api.timeline(pid) : Promise.resolve(null)), 2000)
  const exs = useData(() => api.exceptions(), 2000)
  const cur = list.find((p) => p.id === pid)
  const myExs = (exs.data ?? []).filter((e) => e.proposal_id === pid)

  const [replay, setReplay] = useState<Replay | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [sent, setSent] = useState(false)
  useEffect(() => { setReplay(null); setSent(false); setError(null) }, [pid, me?.role])

  const guard = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setError(null)
    try { await fn() } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) } finally { setBusy(null) }
  }
  const sendEvent = (type: string, payload: Record<string, unknown> = {}) => guard(type, async () => {
    await api.sendEvent(pid, type, payload); setSent(true)
    setTimeout(() => { void tl.reload(true); void exs.reload(true); void props.reload(true) }, 1600)
  })
  const resolve = (e: ExceptionItem, r: 'accept_delay' | 'request_replan') => guard(e.id + r, async () => { await api.resolve(e.id, r); await exs.reload(true); await tl.reload(true) })

  const canDecide = !!me && PARTY_ROLES.has(me.role)
  const isCarrier = me?.role === 'carrier'
  const live = !!cur && ['confirmed', 'executing'].includes(cur.status)
  const km = Math.max(0, Math.round((cur?.deadhead_km ?? 0) * 0.9 * 10) / 10)
  const side = myExs.length > 0 || (isCarrier && live)

  return (
    <>
      <section className="card stack">
        <div className="card-h">
          <h1>{t('tl.title')}</h1>
          {list.length > 0 && (
            <div className="row">
              <label className="inline sr-label" aria-label={t('tl.pick')}>
                <select value={pid} onChange={(e) => setPid(e.target.value)} aria-label={t('tl.pick')}>
                  {list.map((p) => <option key={p.id} value={p.id}>{p.shipment.code} → {p.vehicle.plate} · {t(`ps.${p.status}`)}</option>)}
                </select>
              </label>
              {cur && <Stepper status={cur.status} />}
            </div>)}
        </div>
        {props.loading && !props.data ? <Loading /> : list.length === 0 && <div className="empty">{t('tl.empty')}</div>}
      </section>

      {error && <ErrorNote error={error} />}

      {pid && (
        <div className={side ? 'grid2' : ''} style={{ alignItems: 'start' }}>
          <section className="card stack">
            {tl.error && <ErrorNote error={tl.error} />}
            {tl.loading && !tl.data ? <Loading /> : (
              <ol className="tl">
                {tl.data?.items.map((i, k) => {
                  const title = t(`tl.code.${i.code}`) === `tl.code.${i.code}` ? i.code : t(`tl.code.${i.code}`)
                  const party = typeof i.detail.party === 'string' ? ` (${t(`party.${i.detail.party}`)})` : ''
                  return (
                    <li key={k} className={`tl-item ${i.kind}`}>
                      <span className={`tl-dot ${KIND_COLOR[i.kind]}`} aria-hidden>{KIND_ICON[i.kind]}</span>
                      <div>
                        <div className="row"><b>{title}{party}</b>
                          {i.quality && ABNORMAL.has(i.quality) && <Chip kind="warn">{t(`tl.q.${i.quality}`)}</Chip>}</div>
                        <div className="small muted">{i.actor ? `${i.actor} · ` : ''}{fmtClock(i.at)}
                          {i.latency_s != null && i.latency_s > 0 && <> · {t('tl.latency', { n: i.latency_s })}</>}
                          {typeof i.detail.delay_minutes === 'number' && <> · +{i.detail.delay_minutes}′</>}</div>
                      </div>
                    </li>)
                })}
              </ol>)}
            <div className="row">
              <button className="btn sm" disabled={!!busy} onClick={() => guard('replay', async () => setReplay(await api.replay(pid)))}>{t('tl.replay')}</button>
              {cur && <a className="btn sm" href="#/benefits">{t('tl.benefit')}</a>}
              {replay && <Chip kind={replay.reproducible ? 'PASS' : 'FAIL'}>{replay.reproducible ? '✓' : '✗'} {replay.reproducible ? t('tl.replay.ok') : t('tl.replay.bad')} · {t('tl.replay.line', { a: replay.stored_score ?? '—', b: replay.recomputed_score })}</Chip>}
            </div>
            {replay && (
              <More>
                <div className="stack small">
                  <span>{t('tl.replay.gates', { n: replay.gate_count, r: replay.rejected_candidates })}</span>
                  {replay.baseline && <span>{t('tl.replay.baseline', { id: replay.baseline.id, km: replay.baseline.empty_km, rate: replay.baseline.cost_per_km_vnd.toLocaleString('vi-VN') })}</span>}
                  <span className="footnote">{t('rec.versions', { rule: replay.rule_version, assume: replay.assumption_version, model: replay.model_version })}</span>
                </div>
              </More>)}
          </section>

          {side && (
            <div className="stack">
              {myExs.length > 0 && (
                <section className="card stack">
                  <h2>{t('tl.exceptions')}</h2>
                  {myExs.map((e) => (
                    <div key={e.id} className="stack">
                      <Note kind={e.status === 'open' ? 'warn' : 'info'}>
                        {t(`tl.exc.${e.detail.action ?? 'needs_decision'}`, { n: e.detail.delay_minutes ?? 0 })}
                        {e.status === 'resolved' && <><br /><b>{t('tl.resolved', { r: t(`tl.resolve.${e.detail.resolution ?? 'accept_delay'}`) })}</b></>}
                      </Note>
                      {e.status === 'open' && (canDecide ? (
                        <div className="row">
                          <button className="btn sm primary" disabled={!!busy} onClick={() => resolve(e, 'accept_delay')}>{t('tl.resolve.accept_delay')}</button>
                          <button className="btn sm" disabled={!!busy} onClick={() => resolve(e, 'request_replan')}>{t('tl.resolve.request_replan')}</button>
                        </div>) : <span className="footnote">{t('tl.noPermResolve')}</span>)}
                    </div>))}
                </section>)}
              {isCarrier && live && (
                <section className="card stack">
                  <div className="row">
                    <button className="btn sm" disabled={!!busy || cur?.status !== 'confirmed'} onClick={() => sendEvent('TRIP_STARTED')}>{t('tl.send.start')}</button>
                    <button className="btn sm" disabled={!!busy || cur?.status !== 'executing'} onClick={() => sendEvent('TRIP_COMPLETED', { actual_empty_km: km })}>{t('tl.send.complete', { km })}</button>
                    <button className="btn sm" disabled={!!busy} onClick={() => sendEvent('ETA_UPDATED', { delay_minutes: 30 })}>{t('tl.send.eta')}</button>
                    {sent && <span className="small muted" role="status">{t('tl.sent')}</span>}
                  </div>
                </section>)}
            </div>)}
        </div>)}
    </>
  )
}
