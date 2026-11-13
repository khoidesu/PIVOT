import { useEffect, useState } from 'react'
import { api, ApiError, type GateItem, type MatchRun, type Proposal, type Rejection } from '../api'
import { Chip, ErrorNote, Loading, More, Note, QueryNote } from '../components/ui'
import { fmtNum, fmtTime, fmtVnd, multiTenant, nowMs } from '../fmt'
import { preflight } from '../preflight'
import { reasonText, useI18n, type TFn, tCode } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const CAN_MATCH = new Set(['shipper', 'carrier', 'dispatcher'])

/** Lý do ngắn — dựng từ template + số liệu thật của đề xuất (không do LLM sinh). */
function mainReasons(p: Proposal, t: TFn): string[] {
  const out: string[] = []
  if (p.shipment.weight_kg != null) out.push(t('rec.why.fit', { pct: Math.round(p.score_components.fit * 100) }))
  const pick = p.gates.find((g) => g.gate === 'pickup_window')
  const eta = pick?.detail.eta_pickup as string | undefined
  const dl = pick?.detail.pickup_deadline as string | undefined
  if (eta && dl) out.push(t('rec.why.time', { min: Math.round((new Date(dl).getTime() - new Date(eta).getTime()) / 60000) }))
  if (p.deadhead_km != null) out.push(t('rec.why.km', { km: p.deadhead_km }))
  return out.slice(0, 3)
}

function GateRow({ g }: { g: GateItem }) {
  const { t } = useI18n()
  return (
    <div className="gate-item">
      <Chip kind={g.status}>{g.status}</Chip>
      <span><b>{tCode(t, 'gate.', g.gate)}</b>{g.status !== 'PASS' && <> — {reasonText(g, t, fmtTime)} <span className="code muted">{g.reason_code}</span></>}</span>
    </div>
  )
}

function RejectionList({ title, items, kind }: { title: string; items: Rejection[]; kind: 'FAIL' | 'UNKNOWN' }) {
  const { t } = useI18n()
  if (!items.length) return null
  return (
    <More label={title}>
      <div className="stack">
        {items.map((r) => (
          <div key={r.vehicle_id} className="stack">
            <div><Chip kind={kind}>{kind}</Chip> <b className="mono">{r.plate}</b>{r.yard && <span className="muted small"> · {t('rec.yard', { yard: r.yard, km: r.yard_km ?? '?' })}</span>}</div>
            <ul className="why">{r.reasons.map((x, i) => <li key={i}>{reasonText(x, t, fmtTime)} <span className="code muted">{x.reason_code}</span></li>)}</ul>
          </div>))}
      </div>
    </More>
  )
}

/** Số xe theo từng mã lý do: "22 xe đã xét" ≠ "22 xe quá tải" (một xe có thể trượt nhiều điều kiện). */
export function reasonBreakdown(items: Rejection[]): [string, number][] {
  const n = new Map<string, number>()
  for (const r of items) for (const code of new Set(r.reasons.map((x) => x.reason_code))) n.set(code, (n.get(code) ?? 0) + 1)
  return [...n.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}

function ProposalCard({ p, rank, onHold, busy }: { p: Proposal; rank: number; onHold: (p: Proposal) => void; busy: boolean }) {
  const { t } = useI18n()
  const c = p.score_components
  return (
    <article className="card stack proposal-card" aria-label={p.vehicle.plate}>
      <div className="rank">
        <div><span className="muted small">#{rank}</span> <span className="plate mono">{p.vehicle.plate}</span><div className="muted small">{p.vehicle.carrier_org_name}</div>
          {p.vehicle.yard && <div className="small" title={t('fleet.estTip')}>{t('rec.yard', { yard: p.vehicle.yard, km: p.deadhead_km ?? '?' })}</div>}</div>
        <div className="score"><span className="score-big">{(p.score ?? 0).toFixed(2)}</span><small className="muted">{t('rec.score')}</small></div>
      </div>
      <ul className="why">{mainReasons(p, t).map((r, i) => <li key={i}>{r}</li>)}</ul>
      <div className="small muted">
        {p.eta && <>{t('rec.eta')} <b>{fmtTime(p.eta.pickup)}</b>{p.eta.pickup_p90 && <span className="muted"> – {fmtTime(p.eta.pickup_p90)}</span>}{p.eta.cutoff_risk_p90 && <> <Chip kind="warn" title={t('eta.riskTip')}>{t('eta.risk')}</Chip></>}</>}
        {p.slot && <> · <b>{p.slot.node_org_name}</b> · {t('rec.slot')} <b>{fmtTime(p.slot.start_at)}–{fmtTime(p.slot.end_at).slice(-5)}</b></>}
        {p.estimated_saving_vnd != null && <> · ≈ <b>{fmtVnd(p.estimated_saving_vnd)}</b></>}
      </div>
      {p.my_actions.hold
        ? <button className="btn primary" disabled={busy} onClick={() => onHold(p)}>{busy ? t('rec.holding') : t('rec.hold')}</button>
        : <span className="footnote">{t('rec.noAction')}</span>}
      <More>
        <div className="stack">
          {(['fit', 'time_margin', 'empty_km_saved'] as const).map((k) => (
            <div className="comp" key={k}>
              <span>{tCode(t, 'rec.comp.', k)} <span className="muted">× {c.weights[k]}</span></span><b>{c[k].toFixed(2)}</b>
              <div className="bar" role="presentation"><i style={{ width: `${Math.round(c[k] * 100)}%` }} /></div>
            </div>))}
          <div className="gate-list"><b>{t('rec.gates')}</b>{p.gates.map((g, i) => <GateRow key={i} g={g} />)}</div>
          <div className="small"><b>{t('rec.parties')}</b>: {Object.entries(p.parties).map(([k, v]) => `${tCode(t, 'party.', k)} ${v.org_name}`).join(' · ')}</div>
          <span className="footnote">{p.shipment.weight_kg != null && `${fmtNum(p.shipment.weight_kg)} / ${fmtNum(p.vehicle.capacity_kg)} kg · `}{t('rec.note')}</span>
          <span className="footnote">{t('rec.versions', { rule: p.rule_version, assume: p.assumption_version, model: p.model_version })}</span>
        </div>
      </More>
    </article>
  )
}

export function Recommend({ go, query }: { go: (to: string) => void; query: URLSearchParams }) {
  const { t } = useI18n()
  const { me, meta } = useApp()
  const lots = useData(() => api.shipments(), 10000) // polling chậm: phát hiện mất kết nối và tự hồi (QA-07)
  const open = (lots.data ?? []).filter((s) => s.status === 'open')
  const showOrg = multiTenant(open)
  const [lotId, setLotId] = useState(query.get('lot') ?? '')
  const [pickedIcd, setPickedIcd] = useState('')
  const [run, setRun] = useState<MatchRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [holding, setHolding] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => { setRun(null); setError(null) }, [lotId, me?.role])
  const openIds = open.map((s) => s.id).join(',')
  useEffect(() => { // lô đang chọn rời danh sách chờ ghép (polling: bị giữ/huỷ ở cửa sổ khác) → chọn lô đầu, không ghép nhầm lô cũ
    if (lots.data && (!lotId || !open.some((s) => s.id === lotId))) setLotId(open[0]?.id ?? '')
  }, [openIds, lots.data != null]) // eslint-disable-line react-hooks/exhaustive-deps

  const vehicles = useData(() => api.vehicles())
  const slotList = useData(() => api.slots())
  const destId = open.find((s) => s.id === lotId)?.dest_location_id
  const icds = [...new Map((slotList.data ?? []).filter((s) => s.location_id === destId && s.node_org_name).map((s) => [s.node_org_id, s.node_org_name as string])).entries()]
  const nodeId = icds.some(([id]) => id === pickedIcd) ? pickedIcd : '' // ICD không còn hợp lệ cho lô này → về tự động
  const isStale = (gate: string) => !!run?.rejections.some((r) => r.reasons.some((g) => g.gate === gate && g.reason_code === 'DATA_STALE'))
  const staleLot = run?.status === 'no_feasible_option' && isStale('shipment_fresh')
  const staleVeh = run?.status === 'no_feasible_option' && isStale('data_fresh')
  async function refreshThenRun(kind: 'lot' | 'veh') {
    setBusy(true); setError(null)
    try {
      if (kind === 'lot') await api.refreshShipment(lotId)
      else { for (const v of (vehicles.data ?? []).filter((x) => x.tenant_id === me?.org_id)) await api.sendVehicleEvent(v.id, 'VEHICLE_POSITION'); await new Promise((r) => setTimeout(r, 1600)) }
      setRun(await api.match(lotId, nodeId)); void lots.reload(true)
    } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setBusy(false) }
  }

  const allowed = me ? CAN_MATCH.has(me.role) : false
  const lot = open.find((s) => s.id === lotId)
  const pf = lot ? preflight(lot, vehicles.data ?? [], nowMs(), meta?.stale_shipment_minutes ?? 60, meta?.stale_position_minutes ?? 5) : null
  async function doRun() {
    setBusy(true); setError(null)
    try { setRun(await api.match(lotId, nodeId)) }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setBusy(false) }
  }
  async function hold(p: Proposal) {
    setHolding(p.id); setError(null)
    try { await api.act(p, 'hold'); go('/confirm') }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))); setRun(await api.match(lotId, nodeId).catch(() => run)) }
    finally { setHolding(null) }
  }

  return (
    <>
      <section className="card stack">
        <h1>{t('rec.title')}</h1>
        {me && !allowed && <Note kind="warn">{t('rec.cannot')}</Note>}
        <QueryNote q={lots} />
        {lots.data == null ? (lots.error ? null : <Loading />) : open.length === 0 ? <div className="empty">{t('rec.noOpen')}</div> : (
          <div className="row">
            <label className="inline">{t('rec.pick')}
              <select value={lotId} onChange={(e) => setLotId(e.target.value)} disabled={!allowed}>
                {open.map((s) => <option key={s.id} value={s.id}>{s.code}{showOrg && s.tenant_name ? ` (${s.tenant_name})` : ''} · {tCode(t, 'cargo.', s.cargo_type)} · {s.weight_kg == null ? '?' : `${fmtNum(s.weight_kg)} kg`}{s.missing_fields.length ? ' (!)' : ''}</option>)}
              </select>
            </label>
            <label className="inline">{t('rec.icd')}
              <select value={nodeId} onChange={(e) => setPickedIcd(e.target.value)} disabled={!allowed}>
                <option value="">{t('rec.icdAuto')}</option>
                {icds.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
              </select>
            </label>
            <button className="btn primary" onClick={doRun} disabled={!allowed || busy || !lotId}>{busy ? t('rec.running') : t('rec.run')}</button>
          </div>
        )}
        {pf && lot && (
          <div className="stack">
            <div className="row small" aria-label={t('pf.title')}>
              <span className="muted">{t('pf.title')}:</span>
              <Chip kind={pf.lotStale ? 'warn' : 'good'}>{t('pf.lot', { n: pf.lotAge })}</Chip>
              <Chip kind={pf.pickupPassed ? 'bad' : 'good'}>{t('pf.pickup', { t: fmtTime(lot.pickup_deadline) })}</Chip>
              <Chip kind={pf.cutoffPassed ? 'bad' : 'good'}>{t('pf.cutoff', { t: fmtTime(lot.cutoff_at) })}</Chip>
              {pf.gpsTotal > 0 && <Chip kind={pf.gpsStale ? 'warn' : 'good'}>{t('pf.gps', { n: pf.gpsStale, m: pf.gpsTotal })}</Chip>}
            </div>
            {(pf.pickupPassed || pf.cutoffPassed) && (
              <Note kind="warn">{t('pf.past')}{' '}
                {me?.role === 'shipper' && lot.tenant_id === me.org_id && <button className="btn sm" onClick={() => go(`/request?edit=${lot.id}`)}>{t('pf.edit')}</button>}
              </Note>)}
          </div>)}
      </section>

      {error && <ErrorNote error={error} />}

      {run && (
        <>
          <Note kind={run.status === 'proposals' ? 'ok' : run.status === 'needs_data' ? 'warn' : 'err'}>
            {tCode(t, 'rec.s.', run.status, undefined, { n: run.proposals.length, v: run.evaluated_vehicles })}
          </Note>
          {run.rejections.length > 0 && (
            <div className="small" aria-label={t('rec.breakdown')}>
              <span className="muted">{t('rec.breakdown')}:</span>{' '}
              {reasonBreakdown(run.rejections).map(([code, n], i) => <span key={code}>{i > 0 && ' · '}<span className="code">{code}</span> <b>{n}</b></span>)}
            </div>)}
          {(staleLot || staleVeh) && (
            <Note kind="warn">
              <div className="stack">
                {staleLot && <div>{t('rec.stale.lot')} {me?.role === 'shipper' ? <button className="btn sm" disabled={busy} onClick={() => refreshThenRun('lot')}>{t('rec.stale.refreshLot')}</button> : t('rec.stale.askShipper')}</div>}
                {staleVeh && <div>{t('rec.stale.veh')} {me?.role === 'carrier' ? <button className="btn sm" disabled={busy} onClick={() => refreshThenRun('veh')}>{t('rec.stale.refreshVeh')}</button> : t('rec.stale.askCarrier')}</div>}
                {me?.role === 'dispatcher' && <div className="small">{t('rec.stale.reset')}</div>}
              </div>
            </Note>)}
          {run.proposals.length > 0 && (
            <div className="grid3 proposal-results">{run.proposals.map((p, i) => <ProposalCard key={p.id} p={p} rank={i + 1} onHold={hold} busy={holding === p.id} />)}</div>
          )}
          <RejectionList title={t('rec.rejected', { n: run.rejections.length })} items={run.rejections} kind="FAIL" />
          <RejectionList title={t('rec.unknown', { n: run.needs_data.length })} items={run.needs_data} kind="UNKNOWN" />
        </>
      )}
    </>
  )
}
