import { useEffect, useRef, useState } from 'react'
import { api, ApiError, type EtaSignals, type SimMode, type TripTrack } from '../api'
import { RouteMap } from '../components/RouteMap'
import { Chip, ErrorNote, Hint, Loading, More, Note, QueryNote } from '../components/ui'
import { fmtTime } from '../fmt'
import { useI18n, tCode } from '../i18n'
import { allowedRoute } from '../nav'
import { useApp } from '../store'
import { useData } from '../useData'

const MODES: SimMode[] = ['normal', 'slow', 'breakdown', 'detour']

function EtaBlock({ trip }: { trip: TripTrack }) {
  const { t } = useI18n()
  const e = trip.eta
  if (!e) return null
  const p50 = e.p50 !== undefined ? e.p50 : e.icd
  const p90 = e.p90 !== undefined ? e.p90 : e.icd_p90
  const risk = e.cutoff_risk ?? e.cutoff_risk_p90
  return (
    <div className="stack">
      <div className="row">
        <b>{t('eta.icd')}</b>
        {e.stalled ? <Chip kind="bad">{t('eta.stalled')}</Chip> : <span>{fmtTime(p50 ?? null)} <span className="muted">– {fmtTime(p90 ?? null)}</span></span>}
        {risk && <Chip kind="bad" title={t('eta.riskTip')}>{t('eta.risk')}</Chip>}
      </div>
      <div className="row muted small"><Chip>{e.method.startsWith('rule') ? t('eta.rule') : e.method}</Chip>
        {trip.eta_ml && <Chip kind="teal" title={trip.eta_ml.confidence}>{t('eta.ml', { a: trip.eta_ml.p50_minutes, b: trip.eta_ml.p90_minutes })}</Chip>}
        {trip.cutoff_at && <span>{t('eta.cutoff', { t: fmtTime(trip.cutoff_at) })}</span>}</div>
    </div>
  )
}

function SignalsBlock({ sig }: { sig: EtaSignals }) {
  const { t } = useI18n()
  const c = sig.components, w = sig.weather
  if (sig.status === 'fallback' || sig.status === 'disabled' || !c) {
    return <div className="row muted small"><Chip>{t('eta.rule')}</Chip><span>{t(sig.status === 'disabled' ? 'eta.sig.disabled' : 'eta.sig.fallback')}</span></div>
  }
  return (
    <div className="stack">
      <div className="row">
        <b>{t('eta.sig.title')}</b><Hint text={t('eta.sig.tip')} />
        <span>{fmtTime(sig.p50 ?? null)} <span className="muted">– {fmtTime(sig.p90 ?? null)}</span></span>
        <Chip kind={sig.status === 'ok' ? 'teal' : 'warn'}>{sig.confidence}</Chip>
      </div>
      <div className="row muted small">
        <Chip title={t('tk.road.tip')}>{t('eta.sig.route', { km: c.road_km, min: Math.round(c.free_flow_min) })}</Chip>
        <Chip>{t('eta.sig.truck', { f: c.truck_factor })}</Chip>
        {c.traffic_kind === 'live'
          ? <Chip kind={c.traffic_factor > 1.15 ? 'warn' : 'teal'} title={t('eta.sig.liveTip')}>{t('eta.sig.live', { f: c.traffic_factor })}</Chip>
          : <Chip title={t('eta.sig.trafficTip')}>{t('eta.sig.traffic', { band: tCode(t, 'eta.band.', sig.band ?? 'normal'), f: c.traffic_factor })}</Chip>}
        {w
          ? <Chip kind={c.weather_factor > 1 ? 'warn' : ''}>{t(w.precip_mm_h > 0 ? 'eta.sig.weather' : 'eta.sig.dry', { f: c.weather_factor, mm: w.precip_mm_h })}</Chip>
          : <Chip kind="warn">{t('eta.sig.noWeather')}</Chip>}
      </div>
      {sig.status === 'partial' && <span className="footnote">{t('eta.sig.partial')}</span>}
    </div>
  )
}

function EtaModelCard() {
  const { t } = useI18n()
  const model = useData(() => api.etaModel(), 0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<ApiError | null>(null)
  const m = model.data
  const train = async (drift: number) => { setBusy(true); setErr(null); try { await api.etaTrain(drift); await model.reload(true) } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) } finally { setBusy(false) } }
  if (!m) return null
  const x = m.metrics
  return (
    <More label={t('eta.model')}>
      <div className="stack">
        <div className="row"><Chip kind={m.status === 'promoted' ? 'good' : 'warn'}>{tCode(t, 'eta.status.', m.status)}</Chip>{m.source === 'onnx' && <Chip title={m.sha256 ?? ''}>{m.label}</Chip>}<Chip kind="sim">{t('badge.mock')}</Chip><Hint text={m.note} /></div>
        {x && (
          <table className="mini"><thead><tr><th /><th>{t('eta.rule')}</th><th>ML</th></tr></thead><tbody>
            <tr><td>MAE</td><td>{x.mae_rule}′</td><td>{x.mae_ml}′</td></tr>
            <tr><td>±15′</td><td>{Math.round(x.within15_rule * 100)}%</td><td>{Math.round(x.within15_ml * 100)}%</td></tr>
            <tr><td>P90</td><td>{Math.round(x.p90_coverage_rule * 100)}%</td><td>{Math.round(x.p90_coverage_ml * 100)}%</td></tr>
          </tbody></table>)}
        {x && <span className="footnote">{t('eta.gate', { n: x.improvement_pct, min: x.min_improvement_pct })}{m.baseline ? ` ${t('eta.baseline', { name: m.baseline })}` : ''}</span>}
        {err && <ErrorNote error={err} />}
        {m.reason !== 'ok' && m.status !== 'promoted' && <span className="footnote">{tCode(t, 'eta.reason.', m.reason, 'eta.reason.model_error')}</span>}
        {m.source !== 'onnx' && <div className="row"><button className="btn sm" disabled={busy} onClick={() => train(0)}>{t('eta.train')}</button>
          <button className="btn sm" disabled={busy} onClick={() => train(0.15)}>{t('eta.trainDrift')}</button></div>}
      </div>
    </More>
  )
}

/** Màn trống: nói rõ vì sao (đề xuất chưa đủ 3 bên xác nhận) thay vì để người dùng tưởng hỏng. */
/** Bước còn thiếu để có lợi ích (BUG-05): tới ICD / dỡ hàng KHÔNG tự ghi sổ; chỉ TRIP_COMPLETED của nhà vận tải mới ghi.
 *  Km rỗng thực tế tuỳ chọn: có → dòng "đã đo", để trống → "ước tính". Số liệu vẫn là mô phỏng. */
function CompleteTrip({ trip, isCarrier, onDone }: { trip: TripTrack; isCarrier: boolean; onDone: () => Promise<void> }) {
  const { t } = useI18n()
  const [km, setKm] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<ApiError | null>(null)
  const [sent, setSent] = useState(false)
  const atIcd = trip.milestones.some((m) => m.code === 'AT_ICD_GATE' && m.reached)
  if (trip.status !== 'executing' || !atIcd) return null
  if (!isCarrier) return <Note kind="info">{t('tk.done.wait')}</Note>
  async function send() {
    setBusy(true); setErr(null)
    try {
      await api.sendEvent(trip.proposal_id, 'TRIP_COMPLETED', km.trim() === '' ? {} : { actual_empty_km: Number(km) })
      setSent(true); await onDone()
    } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) } finally { setBusy(false) }
  }
  return (
    <Note kind="warn">
      <div className="stack">
        <span>{t('tk.done.ask')}</span>
        <div className="row">
          <label className="inline small">{t('tk.done.km')}
            <input type="number" min={0} max={500} step={0.1} value={km} onChange={(e) => setKm(e.target.value)} style={{ width: '6rem' }} /></label>
          <button className="btn sm primary" disabled={busy || sent} onClick={send}>{t('tk.done.btn')}</button>
          {sent && <a className="btn sm" href="#/benefits">{t('nav.benefits')}</a>}
        </div>
        {err && <ErrorNote error={err} />}
      </div>
    </Note>
  )
}

function WaitingNote() {
  const { t } = useI18n()
  const { me } = useApp()
  const props = useData(() => api.proposals(), 4000)
  const waiting = (props.data ?? []).filter((p) => p.status === 'pending_acceptance')
  if (props.data == null) return <QueryNote q={props} /> // đang tải / mất kết nối: không báo "chưa có chuyến"
  if (!waiting.length) {
    return (
      <div className="empty stack" style={{ justifyItems: 'center' }}>
        <b>{t('tk.emptyTitle')}</b>
        <span className="muted">{t('tk.emptyHint')}</span>
        {allowedRoute(me?.role, 'recommend') && <a className="btn primary" href="#/recommend">{t('tk.emptyCta')}</a>}
      </div>
    )
  }
  const who = [...new Set(waiting.flatMap((p) => Object.entries(p.parties).filter(([, v]) => !v.accepted).map(([k]) => tCode(t, 'party.', k))))].join(', ')
  return (
    <Note kind="warn">
      <div className="stack">
        <span>{t('tk.waiting', { n: waiting.length })}</span>
        <span className="small">{t('tk.waitingWho', { who })}</span>
        <a className="btn sm" href="#/confirm">{t('nav.confirm')}</a>
      </div>
    </Note>
  )
}

export function Tracking({ query }: { query: URLSearchParams }) {
  const { t } = useI18n()
  const { me } = useApp()
  const list = useData(() => api.tracking(), 2500)
  const [pid, setPid] = useState(query.get('p') ?? '')
  const trips = list.data ?? []
  const tripIds = trips.map((x) => x.proposal_id).join(',')
  useEffect(() => { // chuyến đang chọn biến mất (hoàn tất/huỷ) dù số chuyến không đổi → chọn lại, không để màn hình trống
    if (!trips.length) return
    if (!pid || !trips.some((x) => x.proposal_id === pid)) setPid((trips.find((x) => x.status === 'executing') ?? trips[0]).proposal_id)
  }, [tripIds, pid]) // eslint-disable-line react-hooks/exhaustive-deps
  const detail = useData(() => (pid ? api.trip(pid) : Promise.resolve(null)), 2000, pid) // key=pid: đổi chuyến là tải ngay, không đợi nhịp polling
  const trip = detail.data && detail.data.proposal_id === pid ? detail.data : null
  const roadTried = useRef<Set<string>>(new Set())
  useEffect(() => { // chuyến đã cam kết nhưng chưa chạy: lấy & lưu đường bộ thật một lần (idempotent; lỗi mạng → giữ tuyến mô phỏng)
    if (!trip || trip.status !== 'confirmed' || trip.route_source === 'osrm' || roadTried.current.has(trip.proposal_id)) return
    roadTried.current.add(trip.proposal_id)
    api.roadRoute(trip.proposal_id).then(() => detail.reload(true)).catch(() => { /* giữ tuyến mô phỏng */ })
  }, [trip?.proposal_id, trip?.status, trip?.route_source]) // eslint-disable-line react-hooks/exhaustive-deps
  const [mode, setMode] = useState<SimMode>('normal')
  const [error, setError] = useState<ApiError | null>(null)
  const canSim = me?.role === 'carrier' || me?.role === 'dispatcher'

  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn(); await detail.reload(true); await list.reload(true) } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
  }

  if (list.loading && !list.data) return <Loading />
  // Chuyến vừa hoàn tất rời danh sách "đang chạy" nhưng chi tiết còn hiện → một trạng thái duy nhất: thẻ chuyến + nút Lợi ích (QA-12)
  const justDone = !!trip && trip.status === 'completed' && !trips.length // còn chuyến khác thì effect ở trên tự chọn chuyến đó
  return (
    <section className="stack">
      <div className="card stack">
        <div className="card-h"><h1>{t('tk.title')}</h1><Chip kind="sim">{t('badge.mock')}</Chip></div>
        <QueryNote q={list} />
        {justDone ? (
          <Note kind="ok">
            <span className="row">{t('tk.doneNow', { code: trip.shipment_code })}
              {allowedRoute(me?.role, 'benefits') && <a className="btn sm primary" href="#/benefits">{t('nav.benefits')}</a>}</span>
          </Note>
        ) : list.data == null ? null : !trips.length ? <WaitingNote /> : (
          <div className="row">
            {trips.map((x) => (
              <button key={x.proposal_id} className={`tab${x.proposal_id === pid ? ' on' : ''}`} onClick={() => setPid(x.proposal_id)}>
                {x.shipment_code} · {x.plate}
              </button>))}
          </div>)}
      </div>
      {trip && (
        <div className="split">
          <div className="card"><RouteMap trip={trip} late={trip.position?.speed_kmh === 0} />
            <div className="row muted small"><Chip kind={trip.route_source === 'osrm' ? 'teal' : ''} title={t('tk.road.tip')}>{t(trip.route_source === 'osrm' ? 'tk.road.osrm' : 'tk.road.sim')}</Chip>
              <span>{t('tk.credit')}</span></div></div>
          <div className="card stack">
            <div className="row"><b>{trip.shipment_code}</b><Chip>{trip.plate}</Chip><Chip kind="teal">{tCode(t, 'ps.', trip.status)}</Chip></div>
            <div className="bar" aria-label={`${trip.progress_pct}%`}><i style={{ width: `${trip.progress_pct}%` }} /></div>
            <div className="row muted small"><span>{trip.progress_pct}%</span><span>{t('tk.left', { km: trip.remaining_km })}</span>
              <span>{trip.position?.age_seconds != null ? t('tk.age', { n: trip.position.age_seconds }) : t('tk.nopos')}</span></div>
            <div className="row">
              {trip.milestones.map((ms) => <Chip key={ms.code} kind={ms.reached ? 'good' : ''}>{ms.reached ? '✓ ' : ''}{tCode(t, 'tk.ms.', ms.code)}</Chip>)}
            </div>
            <CompleteTrip trip={trip} isCarrier={me?.role === 'carrier'} onDone={async () => { await detail.reload(true); await list.reload(true) }} />
            <EtaBlock trip={trip} />
            {trip.eta_signals && <SignalsBlock sig={trip.eta_signals} />}
            {canSim && trip.status !== 'completed' && (
              <div className="row">
                <button className="btn" onClick={() => run(() => api.simStart(trip.proposal_id))}>{t('tk.sim')}</button><Hint text={t('tk.simHint')} />
                <select value={mode} aria-label={t('tk.sim')} onChange={(e) => { const v = e.target.value as SimMode; setMode(v); void run(() => api.simMode(trip.proposal_id, v)) }}>
                  {MODES.map((x) => <option key={x} value={x}>{t(`tk.mode.${x}`)}</option>)}
                </select>
              </div>)}
            {error && <Note kind="err">{error.message}</Note>}
          </div>
        </div>)}
      {me?.role === 'dispatcher' && <div className="card"><EtaModelCard /></div>}
    </section>
  )
}
