import { useMemo, useState } from 'react'
import { api, ApiError, type DockAppt } from '../api'
import { Chip, ErrorNote, Hint, Loading, Note } from '../components/ui'
import { fmtTime, isoToLocalInput, localInputToIso, nowMs } from '../fmt'
import { useI18n, tCode } from '../i18n'
import { useData } from '../useData'

const HOUR = 3600_000
const KIND: Record<string, string> = { scheduled: 'teal', checked_in: 'warn', unloading: 'warn', completed: 'good', no_show: 'bad', cancelled: '' }

export function Docks() {
  const { t } = useI18n()
  const board = useData(() => api.dockBoard(), 3000)
  const [sel, setSel] = useState('')
  const [when, setWhen] = useState('')
  const [dockId, setDockId] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const b = board.data

  const [t0, span] = useMemo(() => {
    const start = Math.floor((nowMs() - HOUR) / HOUR) * HOUR
    return [start, 10 * HOUR]
  }, [board.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const pos = (iso: string) => Math.max(0, Math.min(100, ((new Date(iso).getTime() - t0) / span) * 100))
  const block = (a: string, z: string) => ({ left: `${pos(a)}%`, width: `${Math.max(1.5, pos(z) - pos(a))}%` })
  const cur = b?.appointments.find((x) => x.id === sel)

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try { await fn(); await board.reload(true) } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) } finally { setBusy(false) }
  }
  const ev = (a: DockAppt, type: string) => run(() => api.sendEvent(a.proposal_id, type))
  const pick = (a: DockAppt) => { setSel(a.id); setWhen(isoToLocalInput(a.window_start)); setDockId(a.dock_id) }

  if (board.loading && !b) return <Loading />
  const hours = Array.from({ length: 11 }, (_, i) => t0 + i * HOUR)
  const nowPct = pos(new Date(nowMs()).toISOString())
  return (
    <section className="stack">
      <div className="card stack">
        <div className="card-h"><h1>{t('dk.title')}</h1><Chip kind="sim">{t('badge.mock')}</Chip></div>
        {board.error && <ErrorNote error={board.error} />}
        {error && <ErrorNote error={error} />}
        {b && (
          <div className="row kpis">
            <Chip kind="teal">{t('dk.util')} {b.kpis.utilization_pct}%</Chip>
            <Chip>{t('dk.queue')} {b.kpis.queue}</Chip>
            <Chip>{t('dk.dwell')} {b.kpis.avg_dwell_minutes != null ? t('dk.min', { n: b.kpis.avg_dwell_minutes }) : '—'}</Chip>
            <Chip kind={b.kpis.no_show ? 'bad' : ''}>{t('dk.noshow')} {b.kpis.no_show}</Chip>
          </div>)}
        {b && !b.appointments.length && <div className="empty">{t('dk.empty')}</div>}
      </div>
      {b && b.docks.length > 0 && (
        <div className="card">
          <div className="gantt-scroll">
            <div className="gantt">
              <div className="g-head"><span />
                <div className="g-track">{hours.map((h) => <i key={h} style={{ left: `${pos(new Date(h).toISOString())}%` }}>{fmtTime(new Date(h).toISOString()).slice(-5)}</i>)}</div></div>
              {b.docks.map((d) => (
                <div className="g-row" key={d.id}>
                  <span className="g-label"><b>{d.code}</b></span>
                  <div className="g-track">
                    <u className="g-now" style={{ left: `${nowPct}%` }} />
                    {b.busy.filter((x) => x.dock_id === d.id).map((x, i) => <div key={i} className="g-blk busy" style={block(x.window_start, x.window_end)} title={t('dk.busy')} />)}
                    {b.appointments.filter((a) => a.dock_id === d.id && a.status !== 'cancelled').map((a) => (
                      <button key={a.id} className={`g-blk ${a.status}${a.id === sel ? ' sel' : ''}${a.suggestion ? ' sug' : ''}`} style={block(a.window_start, a.window_end)}
                        onClick={() => pick(a)} title={`${a.shipment_code} · ${a.plate}`}>{a.shipment_code}</button>))}
                  </div>
                </div>))}
            </div>
          </div>
        </div>)}
      {b && b.appointments.length > 0 && (
        <div className="card stack">
          {!cur && <div className="muted small">{t('dk.pick')}</div>}
          {cur && (
            <>
              <div className="row">
                <b>{cur.shipment_code}</b><Chip>{cur.plate}</Chip><Chip kind={KIND[cur.status]}>{tCode(t, 'dk.status.', cur.status)}</Chip>
                <span className="muted small">{cur.dock_code} · {fmtTime(cur.window_start)}–{fmtTime(cur.window_end).slice(-5)}</span>
                {cur.late_minutes > 0 && <Chip kind="warn">{t('dk.late', { n: cur.late_minutes })}</Chip>}
                {cur.dwell_minutes != null && <Chip kind="good">{t('dk.dwell')} {t('dk.min', { n: cur.dwell_minutes })}</Chip>}
              </div>
              {cur.suggestion && (
                <Note kind="warn">{t('dk.suggest', { dock: cur.suggestion.dock_code ?? '', t: fmtTime(cur.suggestion.window_start), n: cur.late_minutes })}
                  {cur.can_accept_suggestion && <> <button className="btn sm primary" disabled={busy} onClick={() => run(() => api.dockAccept(cur.id, cur.version))}>{t('dk.accept')}</button></>}</Note>)}
              <div className="row">
                {cur.status === 'scheduled' && <><button className="btn sm" disabled={busy || !cur.can_check_in} onClick={() => ev(cur, 'GATE_CHECK_IN')}>{t('dk.checkin')}</button><Hint text={t('dk.tripNote')} /></>}
                {cur.can_start && <button className="btn sm" disabled={busy} onClick={() => ev(cur, 'UNLOAD_STARTED')}>{t('dk.start')}</button>}
                {cur.can_complete && <button className="btn sm primary" disabled={busy} onClick={() => ev(cur, 'UNLOAD_COMPLETED')}>{t('dk.complete')}</button>}
              </div>
              {cur.can_reschedule && (
                <div className="row">
                  <label className="inline">{t('dk.window')} <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
                  <select aria-label={t('dk.dock')} value={dockId} onChange={(e) => setDockId(e.target.value)}>{b.docks.map((d) => <option key={d.id} value={d.id}>{d.code}</option>)}</select>
                  <button className="btn sm" disabled={busy || !when} onClick={() => run(() => api.dockReschedule(cur.id, cur.version, localInputToIso(when), dockId))}>{t('dk.reschedule')}</button>
                </div>)}
            </>)}
        </div>)}
    </section>
  )
}
