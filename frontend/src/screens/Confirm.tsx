import { useEffect, useState } from 'react'
import { api, ApiError, type Proposal } from '../api'
import { Chip, ErrorNote, Loading, More, Note, Stepper } from '../components/ui'
import { fmtTime, nowMs } from '../fmt'
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
        <div><b>{p.shipment.code}</b> <span className="muted">→</span> <b className="mono">{p.vehicle.plate}</b></div>
        <Stepper status={p.status} />
      </div>
      <div className="row">
        {Object.entries(p.parties).map(([k, v]) => (
          <Chip key={k} kind={v.accepted ? 'good' : p.status === 'pending_acceptance' ? 'warn' : undefined} title={v.org_name ?? undefined}>
            {v.accepted ? '✓' : '○'} {t(`party.${k}`)}
          </Chip>))}
        {p.slot && <Chip title={t('cf.srcTip', { src: p.slot.source })}>{p.slot.node_org_name} · {fmtTime(p.slot.start_at)}–{fmtTime(p.slot.end_at).slice(-5)}</Chip>}
        {left != null && (left > 0 ? <span className="countdown">{t('cf.countdown', { s: left })}</span> : <Chip kind="FAIL">{t('cf.holdExpired')}</Chip>)}
      </div>
      {error && <ErrorNote error={error} />}
      {ok && <Note kind="ok">{ok}</Note>}
      <div className="row">
        <button className="btn primary" disabled={!a.hold || !!busy} onClick={() => run('hold')}>{t('cf.hold')}</button>
        <button className="btn primary" disabled={!a.accept || !!busy} onClick={() => run('accept')}>{t('cf.accept')}</button>
        <button className="btn danger" disabled={!a.reject || !!busy} onClick={() => run('reject')}>{t('cf.reject')}</button>
        {none && <span className="footnote">{t('cf.noPerm')}</span>}
        {['confirmed', 'executing', 'completed'].includes(p.status) && <a className="btn sm" href={`#/timeline?p=${p.id}`}>{t('nav.timeline')} →</a>}
      </div>
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
      <div className="card-h"><h1>{t('cf.title')}</h1><span className="live" role="status"><i aria-hidden />{t('cf.live')}</span></div>
      {props.error && <ErrorNote error={props.error} />}
      {props.loading && !props.data ? <Loading /> : list.length === 0 ? <div className="card empty">{t('cf.empty')}</div> : (
        <>
          <div className="grid2">{live.map((p) => <ProposalRow key={p.id} p={p} onDone={refresh} />)}</div>
          {past.length > 0 && <More label={t('cf.past', { n: past.length })}><div className="grid2">{past.map((p) => <ProposalRow key={p.id} p={p} onDone={refresh} />)}</div></More>}
        </>
      )}
      {me?.role === 'node_operator' && (
        <section className="card">
          <div className="card-h"><h2>{t('cf.slotsTitle')}</h2></div>
          <div className="table-wrap"><table>
            <thead><tr><th>{t('col.time')}</th><th>{t('col.left')}</th></tr></thead>
            <tbody>{(slots.data ?? []).filter((s) => s.node_org_id === me.org_id).map((s) => (
              <tr key={s.id}><td className="nw">{fmtTime(s.start_at)}–{fmtTime(s.end_at).slice(-5)}</td>
                <td><Chip kind={s.remaining === 0 ? 'FAIL' : 'PASS'}>{s.remaining}/{s.capacity}</Chip></td></tr>))}</tbody>
          </table></div>
        </section>)}
    </>
  )
}
