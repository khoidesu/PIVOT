import { useEffect, useState } from 'react'
import { api, ApiError, type SimMode } from '../api'
import { RouteMap } from '../components/RouteMap'
import { Chip, ErrorNote, Hint, Loading, Note } from '../components/ui'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const MODES: SimMode[] = ['normal', 'slow', 'breakdown', 'detour']

export function Tracking({ query }: { query: URLSearchParams }) {
  const { t } = useI18n()
  const { me } = useApp()
  const list = useData(() => api.tracking(), 2500)
  const [pid, setPid] = useState(query.get('p') ?? '')
  const trips = list.data ?? []
  useEffect(() => {
    if (!trips.length) return
    if (!pid || !trips.some((x) => x.proposal_id === pid)) setPid((trips.find((x) => x.status === 'executing') ?? trips[0]).proposal_id)
  }, [trips.length, pid]) // eslint-disable-line react-hooks/exhaustive-deps
  const detail = useData(() => (pid ? api.trip(pid) : Promise.resolve(null)), 2000)
  const trip = detail.data && detail.data.proposal_id === pid ? detail.data : null
  const [mode, setMode] = useState<SimMode>('normal')
  const [error, setError] = useState<ApiError | null>(null)
  const canSim = me?.role === 'carrier' || me?.role === 'dispatcher'

  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn(); await detail.reload(true); await list.reload(true) } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
  }

  if (list.loading && !list.data) return <Loading />
  return (
    <section className="stack">
      <div className="card stack">
        <div className="card-h"><h1>{t('tk.title')}</h1><Chip kind="sim">{t('badge.mock')}</Chip></div>
        {list.error && <ErrorNote error={list.error} />}
        {!trips.length ? <div className="empty">{t('tk.empty')}</div> : (
          <div className="row">
            {trips.map((x) => (
              <button key={x.proposal_id} className={`tab${x.proposal_id === pid ? ' on' : ''}`} onClick={() => setPid(x.proposal_id)}>
                {x.shipment_code} · {x.plate}
              </button>))}
          </div>)}
      </div>
      {trip && (
        <div className="split">
          <div className="card"><RouteMap trip={trip} late={trip.position?.speed_kmh === 0} /><p className="muted small">{t('tk.credit')}</p></div>
          <div className="card stack">
            <div className="row"><b>{trip.shipment_code}</b><Chip>{trip.plate}</Chip><Chip kind="teal">{t(`ps.${trip.status}`)}</Chip></div>
            <div className="bar" aria-label={`${trip.progress_pct}%`}><i style={{ width: `${trip.progress_pct}%` }} /></div>
            <div className="row muted small"><span>{trip.progress_pct}%</span><span>{t('tk.left', { km: trip.remaining_km })}</span>
              <span>{trip.position?.age_seconds != null ? t('tk.age', { n: trip.position.age_seconds }) : t('tk.nopos')}</span></div>
            <div className="row">
              {trip.milestones.map((ms) => <Chip key={ms.code} kind={ms.reached ? 'good' : ''}>{ms.reached ? '✓ ' : ''}{t(`tk.ms.${ms.code}`)}</Chip>)}
            </div>
            {canSim && (
              <div className="row">
                <button className="btn" onClick={() => run(() => api.simStart(trip.proposal_id))}>{t('tk.sim')}</button><Hint text={t('tk.simHint')} />
                <select value={mode} aria-label={t('tk.sim')} onChange={(e) => { const v = e.target.value as SimMode; setMode(v); void run(() => api.simMode(trip.proposal_id, v)) }}>
                  {MODES.map((x) => <option key={x} value={x}>{t(`tk.mode.${x}`)}</option>)}
                </select>
              </div>)}
            {error && <Note kind="err">{error.message}</Note>}
          </div>
        </div>)}
    </section>
  )
}
