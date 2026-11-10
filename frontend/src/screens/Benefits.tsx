import { useEffect, useState } from 'react'
import { api, ApiError, type Benefit } from '../api'
import { Chip, ErrorNote, Loading, Note } from '../components/ui'
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

  return (
    <>
      <section className="card stack">
        <div className="card-h"><h1>{t('bf.title')}</h1><Chip kind="sim">{t('badge.mock')}</Chip></div>
        <span className="muted">{t('bf.intro')}</span>
        <Note kind="warn">{t('bf.disclaimer')}</Note>
        <div className="grid3">
          {STATUSES.map((s) => (
            <div key={s} className="fact">
              <small><Chip kind={KIND[s]}>{t(`bf.status.${s}`)}</Chip> · {t('bf.count', { n: list.data?.totals[s].count ?? 0 })}</small>
              <b style={{ fontSize: 24 }}>{fmtVnd(list.data?.totals[s].net_vnd ?? 0)}</b>
              <small>{t(`bf.sub.${s}`)}</small>
            </div>))}
        </div>
      </section>

      {list.error && <ErrorNote error={list.error} />}
      {list.loading && !list.data ? <Loading /> : items.length === 0 ? <div className="card empty">{t('bf.empty')}</div> : (
        <div className="grid2" style={{ alignItems: 'start' }}>
          <section className="card">
            <div className="table-wrap"><table>
              <thead><tr><th>{t('bf.col.lot')}</th><th>{t('bf.col.vehicle')}</th><th className="num">{t('bf.col.base')}</th><th className="num">{t('bf.col.actual')}</th>
                <th className="num">{t('bf.col.net')}</th><th>{t('bf.col.status')}</th></tr></thead>
              <tbody>{items.map((b) => (
                <tr key={b.id} onClick={() => setSel(b.id)} style={{ cursor: 'pointer', background: b.id === sel ? 'var(--teal-weak)' : undefined }} aria-selected={b.id === sel}>
                  <td><b>{b.shipment_code}</b></td><td className="mono">{b.vehicle_plate}</td>
                  <td className="num">{fmtNum(b.quantity_before)}</td><td className="num">{fmtNum(b.quantity_after)}</td>
                  <td className="num"><b>{fmtVnd(b.net_vnd)}</b></td>
                  <td><Chip kind={KIND[b.status]}>{t(`bf.status.${b.status}`)}</Chip></td>
                </tr>))}</tbody>
            </table></div>
          </section>

          <section className="card stack">
            <div className="card-h"><h2>{t('bf.detail')}</h2></div>
            {error && <ErrorNote error={error} />}
            {!detail ? <span className="muted">{t('bf.select')}</span> : (
              <>
                <div className="row"><b>{detail.shipment_code}</b> <span className="mono">{detail.vehicle_plate}</span><Chip kind={KIND[detail.status]}>{t(`bf.status.${detail.status}`)}</Chip></div>
                <div className="fact">
                  <small>{detail.beneficiary_org_name}</small>
                  <b>{t('bf.formula', { before: fmtNum(detail.formula?.before), after: fmtNum(detail.formula?.after), rate: fmtNum(detail.formula?.rate), net: fmtVnd(detail.net_vnd) })}</b>
                </div>
                {detail.baseline && <span className="small">{t('bf.baseline', { id: detail.baseline_id, km: detail.baseline.empty_km, time: fmtTime(detail.baseline.fixed_at) })}</span>}
                <span className="small">{t('bf.assumption', { v: detail.assumption_version, m: String(detail.assumptions.eta_method ?? 'rule-based') })}</span>
                <div className="stack">
                  <h3>{t('bf.evidence')}</h3>
                  {detail.evidence.map((e) => (
                    <div key={e.id} className="small">• {t('bf.evidenceRow', { type: e.event_type, src: e.source_system, occ: fmtClock(e.occurred_at), rec: fmtClock(e.received_at), q: e.quality_status })}
                      {e.payload && 'actual_empty_km' in e.payload && <> · actual_empty_km = <b>{String(e.payload.actual_empty_km)}</b></>}</div>))}
                </div>
                {detail.status === 'verified'
                  ? <Note kind="ok">{t('bf.verified', { who: detail.verifier ?? '', time: fmtTime(detail.verified_at) })}</Note>
                  : <div className="stack">
                      <div><button className="btn primary" disabled={!detail.can_verify || busy} onClick={verify}>{t('bf.verify')}</button></div>
                      {!detail.can_verify && <span className="footnote">{detail.status === 'estimated' ? t('bf.cantEstimated') : !detail.verifier_independent_available ? t('bf.noIndependent') : me && !['shipper', 'carrier'].includes(me.role) ? t('bf.cantRole') : t('bf.cantReporter')}</span>}
                    </div>}
                {detail.proposal_id && <a className="btn sm" href={`#/timeline?p=${detail.proposal_id}`} style={{ textAlign: 'center', textDecoration: 'none' }}>{t('bf.openTimeline')}</a>}
              </>)}
          </section>
        </div>)}
    </>
  )
}
