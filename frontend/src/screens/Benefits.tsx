import { useEffect, useState } from 'react'
import { api, ApiError, type Benefit } from '../api'
import { Chip, ErrorNote, Hint, Loading, More, Note } from '../components/ui'
import { fmtClock, fmtNum, fmtTime, fmtVnd } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const STATUSES = ['estimated', 'measured', 'verified'] as const
const KIND = { estimated: 'warn', measured: 'teal', verified: 'good' } as const

export function Benefits({ query }: { query: URLSearchParams }) {
  const { t } = useI18n()
  const { me } = useApp()
  const list = useData(() => api.benefits(), 3000)
  const [sel, setSel] = useState(query.get('b') ?? '')
  const [detail, setDetail] = useState<Benefit | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const items = list.data?.items ?? []

  useEffect(() => { if (!sel && items.length) setSel(items[0].id) }, [items.length]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!sel) { setDetail(null); return }
    api.benefit(sel).then(setDetail).catch((e) => setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))))
  }, [sel, list.data])

  async function verify() {
    if (!detail) return
    setBusy(true); setError(null)
    try { setDetail(await api.verify(detail.id)); void list.reload(true) }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setBusy(false) }
  }
  const whyNot = (d: Benefit) => d.status === 'estimated' ? t('bf.cantEstimated') : !d.verifier_independent_available ? t('bf.noIndependent')
    : me && !['shipper', 'carrier'].includes(me.role) ? t('bf.cantRole') : t('bf.cantReporter')

  return (
    <>
      <section className="card stack">
        <div className="card-h"><h1>{t('bf.title')}</h1><span className="muted small">{t('bf.sim')} <Hint text={t('bf.simTip')} /></span></div>
        <div className="grid3">
          {STATUSES.map((s) => (
            <div key={s} className="fact">
              <small><Chip kind={KIND[s]}>{t(`bf.status.${s}`)}</Chip> <Hint text={t(`bf.sub.${s}`)} /> · {t('bf.count', { n: list.data?.totals[s].count ?? 0 })}</small>
              <b style={{ fontSize: 22 }}>{fmtVnd(list.data?.totals[s].net_vnd ?? 0)}</b>
            </div>))}
        </div>
      </section>

      {list.error && <ErrorNote error={list.error} />}
      {list.loading && !list.data ? <Loading /> : items.length === 0 ? <div className="card empty stack"><span>{t('bf.empty')}</span><span className="small muted">{t('bf.emptyHow')}</span><a className="btn sm" href="#/tracking">{t('nav.tracking')}</a></div> : (
        <div className="grid2" style={{ alignItems: 'start' }}>
          <section className="card">
            <div className="table-wrap"><table>
              <thead><tr><th>{t('bf.col.trip')}</th><th className="num">{t('bf.col.km')}</th><th className="num">{t('bf.col.net')}</th><th>{t('bf.col.status')}</th></tr></thead>
              <tbody>{items.map((b) => (
                <tr key={b.id} onClick={() => setSel(b.id)} style={{ cursor: 'pointer', background: b.id === sel ? 'var(--teal-weak)' : undefined }} aria-selected={b.id === sel}>
                  <td><b>{b.shipment_code}</b> <span className="mono muted small">{b.vehicle_plate}</span></td>
                  <td className="num nw">{fmtNum(b.quantity_before)} → {fmtNum(b.quantity_after)}</td>
                  <td className="num"><b>{fmtVnd(b.net_vnd)}</b></td>
                  <td><Chip kind={KIND[b.status]}>{t(`bf.status.${b.status}`)}</Chip></td>
                </tr>))}</tbody>
            </table></div>
          </section>

          <section className="card stack">
            {error && <ErrorNote error={error} />}
            {!detail ? <span className="muted">{t('bf.select')}</span> : (
              <>
                <div className="row"><b>{detail.shipment_code}</b> <span className="mono muted">{detail.vehicle_plate}</span><Chip kind={KIND[detail.status]}>{t(`bf.status.${detail.status}`)}</Chip></div>
                <div className="fact"><b>{t('bf.formula', { before: fmtNum(detail.formula?.before), after: fmtNum(detail.formula?.after), rate: fmtNum(detail.formula?.rate), net: fmtVnd(detail.net_vnd) })}</b></div>
                {detail.status === 'verified'
                  ? <Note kind="ok">{t('bf.verified', { who: detail.verifier ?? '' })}</Note>
                  : <div className="row">
                      <button className="btn primary" disabled={!detail.can_verify || busy} onClick={verify}>{t('bf.verify')}</button>
                      {!detail.can_verify && <span className="footnote">{whyNot(detail)}</span>}
                    </div>}
                <More>
                  <div className="stack small">
                    {detail.baseline && <span>{t('bf.baseline', { id: detail.baseline_id, km: detail.baseline.empty_km, time: fmtTime(detail.baseline.fixed_at) })}</span>}
                    <span>{t('bf.assumption', { v: detail.assumption_version, m: String(detail.assumptions.eta_method ?? 'rule-based') })}</span>
                    <b>{t('bf.evidence')}</b>
                    {detail.evidence.map((e) => (
                      <span key={e.id}>• {t('bf.evidenceRow', { type: e.event_type, src: e.source_system, occ: fmtClock(e.occurred_at) })}
                        {e.payload && 'actual_empty_km' in e.payload && <> · {String(e.payload.actual_empty_km)} km</>}</span>))}
                  </div>
                </More>
                {detail.proposal_id && <a className="btn sm" href={`#/timeline?p=${detail.proposal_id}`}>{t('bf.timeline')}</a>}
              </>)}
          </section>
        </div>)}
    </>
  )
}
