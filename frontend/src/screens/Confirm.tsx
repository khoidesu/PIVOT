import { useEffect, useState } from 'react'
import { api, ApiError, type Proposal } from '../api'
import { Chip, ErrorNote, Loading, Note, Stepper } from '../components/ui'
import { fmtClock, fmtTime, nowMs } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

function useTick() {
  const [, set] = useState(0)
  useEffect(() => { const id = setInterval(() => set((n) => n + 1), 1000); return () => clearInterval(id) }, [])
}

function ProposalRow({ p, onDone }: { p: Proposal; onDone: () => void }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  useTick()
  const left = p.status === 'pending_acceptance' && p.expires_at
    ? Math.max(0, Math.round((new Date(p.expires_at).getTime() - nowMs()) / 1000)) : null

  async function run(action: 'hold' | 'accept' | 'reject') {
    setBusy(action); setError(null); setOk(null)
    try { await api.act(p, action); setOk(t(`cf.ok.${action}`)) }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setBusy(null); onDone() } // luôn tải lại: version/trạng thái có thể đã đổi
  }
  const a = p.my_actions
  const none = !a.hold && !a.accept && !a.reject

  return (
    <article className="card stack" aria-label={`${p.shipment.code} ${p.vehicle.plate}`}>
      <div className="spread">
        <div><b>{p.shipment.code}</b> <span className="muted">→</span> <b className="mono">{p.vehicle.plate}</b>
          <span className="muted small"> · {p.vehicle.carrier_org_name}</span></div>
        <div className="row">
          <Chip kind={p.status === 'confirmed' || p.status === 'completed' ? 'good' : ['rejected', 'expired', 'cancelled'].includes(p.status) ? 'bad' : 'teal'}>{t(`ps.${p.status}`)}</Chip>
          <Chip kind="sim">{t('badge.mock')}</Chip><span className="code muted">v{p.version}</span>
        </div>
      </div>
      <Stepper status={p.status} />
      <div className="facts">
        <div className="fact"><small>{t('rec.slot')}</small>
          {p.slot ? <><b>{fmtTime(p.slot.start_at)}–{fmtTime(p.slot.end_at).slice(-5)}</b><small>{p.slot.node_org_name} · {t('rec.slotSeats', { n: p.slot.remaining, cap: p.slot.capacity })}</small></> : '—'}</div>
        <div className="fact"><small>{t('cf.source', { src: '' }).replace(/:\s*$/, '')}</small>
          <b>{p.confirmation_source ?? '—'}</b><small>{t(`cf.src.${p.confirmation_source ?? 'mock'}`)}</small></div>
      </div>
      <div className="row">
        {Object.entries(p.parties).map(([k, v]) => (
          <Chip key={k} kind={v.accepted ? 'good' : p.status === 'pending_acceptance' ? 'warn' : undefined}>
            {v.accepted ? '✓' : '○'} {t(`party.${k}`)} · {v.org_name} — {v.accepted ? t('cf.accepted') : t('cf.waiting')}
          </Chip>))}
      </div>
      {left != null && <div>{left > 0 ? <span className="countdown">{t('cf.countdown', { s: left })}</span> : <Chip kind="FAIL">{t('cf.holdExpired')}</Chip>}</div>}
      {error && <ErrorNote error={error} />}
      {ok && <Note kind="ok">{ok}</Note>}
      <div className="row">
        <button className="btn primary" disabled={!a.hold || !!busy} onClick={() => run('hold')}>{t('cf.hold')}</button>
        <button className="btn primary" disabled={!a.accept || !!busy} onClick={() => run('accept')}>{t('cf.accept')}</button>
        <button className="btn danger" disabled={!a.reject || !!busy} onClick={() => run('reject')}>{t('cf.reject')}</button>
        {none && <span className="footnote">{t('cf.noPerm')}</span>}
      </div>
      {['confirmed', 'executing'].includes(p.status) && <span className="footnote">{t('cf.execNote')}</span>}
    </article>
  )
}

export function Confirm() {
  const { t } = useI18n()
  const { me } = useApp()
  const props = useData(() => api.proposals(), 2000) // polling 2s (DRAFT bảng 2: polling trước)
  const slots = useData(() => api.slots(), 2000)
  const list = props.data ?? []
  const live = list.filter((p) => ['proposed', 'pending_acceptance', 'confirmed', 'executing'].includes(p.status))
  const past = list.filter((p) => !live.includes(p))
  const refresh = () => { void props.reload(true); void slots.reload(true) }

  return (
    <>
      <section className="card">
        <div className="card-h"><h1>{t('cf.title')}</h1><span className="muted">{t('cf.intro')}</span></div>
        <span className="footnote">{t('cf.refresh')} {me && <>· {t(`role.${me.role}`)}</>}</span>
      </section>
      {props.error && <ErrorNote error={props.error} />}
      {props.loading && !props.data ? <Loading /> : list.length === 0 ? <div className="card empty">{t('cf.empty')}</div> : (
        <>
          <div className="grid2">{live.map((p) => <ProposalRow key={p.id} p={p} onDone={refresh} />)}</div>
          {past.length > 0 && (
            <details><summary>{t('ps.completed')} / {t('ps.expired')} / {t('ps.rejected')} ({past.length})</summary>
              <div className="grid2" style={{ marginTop: 12 }}>{past.map((p) => <ProposalRow key={p.id} p={p} onDone={refresh} />)}</div>
            </details>)}
        </>
      )}
      <section className="card">
        <div className="card-h"><h2>{t('cf.slotsTitle')}</h2><Chip kind="sim">{t('badge.mock')}</Chip></div>
        <div className="table-wrap"><table>
          <thead><tr><th>{t('fleet.slotCol.time')}</th><th>{t('fleet.slotCol.left')}</th><th>{t('fleet.slotCol.source')}</th></tr></thead>
          <tbody>{(slots.data ?? []).map((s) => (
            <tr key={s.id}><td className="nw">{fmtTime(s.start_at)}–{fmtTime(s.end_at).slice(-5)}</td>
              <td><Chip kind={s.remaining === 0 ? 'FAIL' : 'PASS'}>{s.remaining}/{s.capacity}</Chip></td>
              <td><Chip kind="sim">{s.source}</Chip></td></tr>))}</tbody>
        </table></div>
        <span className="footnote">{slots.data ? fmtClock(new Date(nowMs()).toISOString()) : ''}</span>
      </section>
    </>
  )
}
