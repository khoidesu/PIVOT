import { useEffect, useState } from 'react'
import { api, ApiError, type ExceptionItem, type Replay } from '../api'
import { Chip, ErrorNote, Loading, Note, Stepper } from '../components/ui'
import { fmtClock } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const KIND_ICON: Record<string, string> = { match: '◎', decision: '✔', event: '⇄', exception: '⚠', benefit: '₫' }
const KIND_COLOR: Record<string, string> = { match: 'teal', decision: 'good', event: '', exception: 'warn', benefit: 'good' }
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
  const live = cur && ['confirmed', 'executing'].includes(cur.status)

  return (
    <>
      <section className="card stack">
        <div className="card-h"><h1>{t('tl.title')}</h1><span className="muted">{t('tl.intro')}</span></div>
        {props.loading && !props.data ? <Loading /> : list.length === 0 ? <div className="empty">{t('tl.empty')}</div> : (
          <div className="row">
            <label style={{ minWidth: 300 }}>{t('tl.pick')}
              <select value={pid} onChange={(e) => setPid(e.target.value)}>
                {list.map((p) => <option key={p.id} value={p.id}>{p.shipment.code} → {p.vehicle.plate} · {t(`ps.${p.status}`)}</option>)}
              </select>
            </label>
            {cur && <div style={{ alignSelf: 'end' }}><Stepper status={cur.status} /></div>}
          </div>
        )}
      </section>

      {error && <ErrorNote error={error} />}

      {pid && (
        <div className="grid2" style={{ alignItems: 'start' }}>
          <section className="card">
            <div className="card-h"><h2>{t('tl.items')}</h2>{tl.data && <span className="code muted">v{tl.data.version}</span>}</div>
            {tl.error && <ErrorNote error={tl.error} />}
            {tl.loading && !tl.data ? <Loading /> : (
              <ol className="tl">
                {tl.data?.items.map((i, k) => (
                  <li key={k} className={`tl-item ${i.kind}`}>
                    <span className={`tl-dot ${KIND_COLOR[i.kind]}`} aria-hidden>{KIND_ICON[i.kind]}</span>
                    <div>
                      <div className="row"><b>{t(`tl.code.${i.code}`) === `tl.code.${i.code}` ? i.code : t(`tl.code.${i.code}`)}</b>
                        <Chip>{t(`tl.kind.${i.kind}`)}</Chip>
                        {i.quality && i.quality !== 'ok' && <Chip kind={i.quality === 'late' || i.quality === 'invalid' ? 'warn' : i.quality === 'resolved' || i.quality === 'applied' ? 'good' : undefined}>{t(`tl.q.${i.quality}`) === `tl.q.${i.quality}` ? i.quality : t(`tl.q.${i.quality}`)}</Chip>}
                      </div>
                      <div className="small muted">{fmtClock(i.at)} · {i.actor ?? '—'}
                        {i.latency_s != null && <> · {t('tl.latency', { n: i.latency_s })}</>}
                        {typeof i.detail.party === 'string' && <> · {t('tl.party', { p: i.detail.party })}</>}
                        {typeof i.detail.delay_minutes === 'number' && <> · +{i.detail.delay_minutes} min</>}</div>
                    </div>
                  </li>))}
              </ol>)}
          </section>

          <div className="stack">
            <section className="card stack">
              <div className="card-h"><h2>{t('tl.exceptions')}</h2></div>
              {myExs.length === 0 ? <span className="muted">{t('tl.noExceptions')}</span> : myExs.map((e) => (
                <div key={e.id} className="stack">
                  <Note kind={e.status === 'open' ? 'warn' : 'info'}>
                    <b>{t('tl.code.ETA_CHANGED')}</b> · <Chip kind={e.status === 'open' ? 'warn' : 'good'}>{t(`tl.q.${e.status}`)}</Chip><br />
                    {t(`tl.exc.${e.detail.action ?? 'needs_decision'}`, { n: e.detail.delay_minutes ?? 0 })}
                    {e.status === 'resolved' && <><br /><b>{t('tl.resolved', { r: t(`tl.resolve.${e.detail.resolution ?? 'accept_delay'}`), who: e.detail.resolved_by ?? '' })}</b></>}
                  </Note>
                  {e.status === 'open' && (canDecide ? (
                    <div className="row">
                      <button className="btn sm primary" disabled={!!busy} onClick={() => resolve(e, 'accept_delay')}>{t('tl.resolve.accept_delay')}</button>
                      <button className="btn sm" disabled={!!busy} onClick={() => resolve(e, 'request_replan')}>{t('tl.resolve.request_replan')}</button>
                    </div>) : <span className="footnote">{t('tl.noPermResolve')}</span>)}
                </div>))}
            </section>

            {isCarrier && live && (
              <section className="card stack">
                <div className="card-h"><h2>{t('tl.send')}</h2></div>
                <div className="row">
                  <button className="btn sm" disabled={!!busy || cur?.status !== 'confirmed'} onClick={() => sendEvent('TRIP_STARTED')}>{t('tl.send.start')}</button>
                  <button className="btn sm" disabled={!!busy || cur?.status !== 'executing'} onClick={() => sendEvent('TRIP_COMPLETED', { actual_empty_km: Math.max(0, Math.round((cur?.deadhead_km ?? 0) * 0.9 * 10) / 10) })}>
                    {t('tl.send.complete', { km: Math.max(0, Math.round((cur?.deadhead_km ?? 0) * 0.9 * 10) / 10) })}</button>
                  <button className="btn sm" disabled={!!busy} onClick={() => sendEvent('ETA_UPDATED', { delay_minutes: 30 })}>{t('tl.send.eta')}</button>
                </div>
                {sent && <Note kind="ok">{t('tl.sent')}</Note>}
                <span className="footnote">{t('cf.execNote')}</span>
              </section>)}

            <section className="card stack">
              <div className="card-h"><h2>{t('tl.replay')}</h2><span className="muted small">{t('tl.replayHint')}</span></div>
              <div><button className="btn sm" disabled={!!busy} onClick={() => guard('replay', async () => setReplay(await api.replay(pid)))}>{t('tl.replayRun')}</button></div>
              {replay && (
                <div className="stack">
                  <Note kind={replay.reproducible ? 'ok' : 'err'}><b>{replay.reproducible ? t('tl.replay.ok') : t('tl.replay.bad')}</b><br />
                    {t('tl.replay.scores', { a: replay.stored_score ?? '—', b: replay.recomputed_score })}</Note>
                  <span className="small">{t('tl.replay.gates', { n: replay.gate_count, r: replay.rejected_candidates })}</span>
                  {replay.baseline && <span className="small">{t('tl.replay.baseline', { id: replay.baseline.id, km: replay.baseline.empty_km, rate: replay.baseline.cost_per_km_vnd.toLocaleString('vi-VN') })}</span>}
                  <span className="footnote">{t('tl.replay.versions', { rule: replay.rule_version, assume: replay.assumption_version, model: replay.model_version })}</span>
                </div>)}
            </section>
            {cur && <a className="btn sm" href="#/benefits" style={{ textAlign: 'center', textDecoration: 'none' }}>{t('tl.benefit')}</a>}
          </div>
        </div>
      )}
    </>
  )
}
