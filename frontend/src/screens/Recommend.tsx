import { useEffect, useState } from 'react'
import { api, ApiError, type GateItem, type MatchRun, type Proposal, type Rejection } from '../api'
import { Chip, ErrorNote, Loading, Note } from '../components/ui'
import { fmtClock, fmtNum, fmtTime, fmtVnd } from '../fmt'
import { reasonText, useI18n, type TFn } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const CAN_MATCH = new Set(['shipper', 'carrier', 'dispatcher'])

/** 3 lý do chính — dựng từ template + số liệu thật của đề xuất (không do LLM sinh). */
function mainReasons(p: Proposal, t: TFn): string[] {
  const out: string[] = []
  const w = p.shipment.weight_kg
  if (w != null) out.push(t('rec.why.fit', { pct: Math.round(p.score_components.fit * 100), weight: fmtNum(w), cap: fmtNum(p.vehicle.capacity_kg) }))
  const pick = p.gates.find((g) => g.gate === 'pickup_window')
  const eta = pick?.detail.eta_pickup as string | undefined
  const dl = pick?.detail.pickup_deadline as string | undefined
  if (eta && dl) out.push(t('rec.why.time', { min: Math.round((new Date(dl).getTime() - new Date(eta).getTime()) / 60000), deadline: fmtTime(dl) }))
  if (p.deadhead_km != null) out.push(t('rec.why.km', { km: p.deadhead_km }))
  return out.slice(0, 3)
}

function GateRow({ g }: { g: GateItem }) {
  const { t } = useI18n()
  return (
    <div className="gate-item">
      <Chip kind={g.status}>{g.status}</Chip>
      <span><b>{t(`gate.${g.gate}`)}</b>{g.status !== 'PASS' && <> — {reasonText(g, t, fmtTime)}</>}
        {g.status !== 'PASS' && <> <span className="code muted">{g.reason_code}</span></>}</span>
    </div>
  )
}

function RejectionList({ title, items, kind }: { title: string; items: Rejection[]; kind: 'FAIL' | 'UNKNOWN' }) {
  const { t } = useI18n()
  if (!items.length) return null
  return (
    <details>
      <summary>{title}</summary>
      <div className="stack" style={{ marginTop: 10 }}>
        {items.map((r) => (
          <div key={r.vehicle_id} className="stack">
            <div><Chip kind={kind}>{kind}</Chip> <b className="mono">{r.plate}</b></div>
            <ul className="why">{r.reasons.map((x, i) => (
              <li key={i}>{reasonText(x, t, fmtTime)} <span className="code muted">{x.reason_code}</span></li>))}</ul>
          </div>))}
      </div>
    </details>
  )
}

function ProposalCard({ p, rank, run, onHold, busy }: { p: Proposal; rank: number; run: MatchRun; onHold: (p: Proposal) => void; busy: boolean }) {
  const { t } = useI18n()
  const c = p.score_components
  return (
    <article className="card stack" aria-label={p.vehicle.plate}>
      <div className="rank">
        <div><Chip kind="teal">{t('rec.rank', { n: rank })}</Chip><div className="plate mono">{p.vehicle.plate}</div>
          <span className="muted small">{p.vehicle.carrier_org_name}</span></div>
        <div style={{ textAlign: 'right' }}><div className="score-big">{(p.score ?? 0).toFixed(2)}</div><span className="muted small">{t('rec.score')}</span></div>
      </div>
      <div className="stack">
        {(['fit', 'time_margin', 'empty_km_saved'] as const).map((k) => (
          <div className="comp" key={k}>
            <span>{t(`rec.comp.${k}`)} <span className="muted">× {c.weights[k]}</span></span><b>{c[k].toFixed(2)}</b>
            <div className="bar" role="presentation"><i style={{ width: `${Math.round(c[k] * 100)}%` }} /></div>
          </div>))}
        <span className="footnote">{t('rec.scoreHint')}</span>
      </div>
      <div>
        <h3>{t('rec.reasons')}</h3>
        <ul className="why">{mainReasons(p, t).map((r, i) => <li key={i}>{r}</li>)}</ul>
      </div>
      <div className="facts">
        <div className="fact"><small>{t('rec.eta')}</small><b>{fmtTime(p.eta?.pickup)}</b><small>{t('rec.etaNote')}</small></div>
        <div className="fact"><small>{t('rec.saving')} ({t('common.estimated')})</small><b>{fmtVnd(p.estimated_saving_vnd)}</b><small>{t('rec.savingNote')}</small></div>
        {p.slot && <div className="fact"><small>{t('rec.slot')} · {p.slot.node_org_name}</small><b>{fmtTime(p.slot.start_at)}–{fmtTime(p.slot.end_at).slice(-5)}</b>
          <small>{t('rec.slotSeats', { n: p.slot.remaining, cap: p.slot.capacity })} · <Chip kind="sim">{p.slot.source}</Chip></small></div>}
        <div className="fact"><small>{t('rec.approvers')}</small>
          {Object.entries(p.parties).map(([k, v]) => <div key={k} className="small">{t(`party.${k}`)}: <b>{v.org_name}</b></div>)}</div>
      </div>
      <details><summary>{t('rec.gates')} ({p.gates.length})</summary><div className="gate-list">{p.gates.map((g, i) => <GateRow key={i} g={g} />)}</div></details>
      <div className="spread">
        <span className="footnote">{t('rec.versions', { rule: p.rule_version, assume: p.assumption_version, model: p.model_version })}</span>
        {p.my_actions.hold
          ? <button className="btn primary" disabled={busy} onClick={() => onHold(p)}>{busy ? t('rec.holding') : t('rec.hold', { s: 120 })}</button>
          : <span className="footnote">{t('rec.noAction')}</span>}
      </div>
      <span className="footnote">{t('rec.runAt', { time: fmtClock(run.generated_at) })}</span>
    </article>
  )
}

export function Recommend({ go, query }: { go: (to: string) => void; query: URLSearchParams }) {
  const { t } = useI18n()
  const { me } = useApp()
  const lots = useData(() => api.shipments())
  const open = (lots.data ?? []).filter((s) => s.status === 'open')
  const [lotId, setLotId] = useState(query.get('lot') ?? '')
  const [run, setRun] = useState<MatchRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [holding, setHolding] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  useEffect(() => { setRun(null); setError(null) }, [lotId, me?.role])
  useEffect(() => { if (!lotId && open.length) setLotId(open[0].id) }, [open.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const allowed = me ? CAN_MATCH.has(me.role) : false
  async function doRun() {
    setBusy(true); setError(null)
    try { setRun(await api.match(lotId)) }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setBusy(false) }
  }
  async function hold(p: Proposal) {
    setHolding(p.id); setError(null)
    try { await api.act(p, 'hold'); go('/confirm') }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))); setRun(await api.match(lotId).catch(() => run)) }
    finally { setHolding(null) }
  }

  return (
    <>
      <section className="card">
        <div className="card-h"><h1>{t('rec.title')}</h1></div>
        {me && !allowed && <Note kind="warn">{t('rec.cannot', { role: t(`role.${me.role}`) })}</Note>}
        {lots.loading && !lots.data ? <Loading /> : open.length === 0 ? <div className="empty">{t('rec.noOpen')}</div> : (
          <div className="row">
            <label style={{ minWidth: 280 }}>{t('rec.pick')}
              <select value={lotId} onChange={(e) => setLotId(e.target.value)} disabled={!allowed}>
                {open.map((s) => <option key={s.id} value={s.id}>{s.code} · {t(`cargo.${s.cargo_type}`)} · {s.weight_kg == null ? '?' : `${fmtNum(s.weight_kg)} kg`}{s.missing_fields.length ? ' ⚠' : ''}</option>)}
              </select>
            </label>
            <button className="btn primary" style={{ alignSelf: 'end' }} onClick={doRun} disabled={!allowed || busy || !lotId}>{busy ? t('rec.running') : t('rec.run')}</button>
          </div>
        )}
      </section>

      {error && <ErrorNote error={error} />}

      {run && (
        <>
          <Note kind={run.status === 'proposals' ? 'ok' : run.status === 'needs_data' ? 'warn' : 'err'}>
            <b>{t(`rec.s.${run.status}`, { n: run.proposals.length })}</b><br />
            <span className="small">{t('rec.evaluated', { n: run.evaluated_vehicles })} · {run.eta_method}</span>
          </Note>
          {run.proposals.length > 0 && (
            <div className="grid3">{run.proposals.map((p, i) => (
              <ProposalCard key={p.id} p={p} rank={i + 1} run={run} onHold={hold} busy={holding === p.id} />))}</div>
          )}
          <RejectionList title={t('rec.rejected', { n: run.rejections.length })} items={run.rejections} kind="FAIL" />
          <RejectionList title={t('rec.unknown', { n: run.needs_data.length })} items={run.needs_data} kind="UNKNOWN" />
        </>
      )}
    </>
  )
}
