import { useEffect, useState } from 'react'
import { api, ApiError, type Proposal } from '../api'
import { Chip, ErrorNote, Loading, More, Note } from '../components/ui'
import { ageMinutes, fmtTime, nowMs } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

function useTick() {
  const [, set] = useState(0)
  useEffect(() => { const id = setInterval(() => set((n) => n + 1), 1000); return () => clearInterval(id) }, [])
}

const LIVE = ['pending_acceptance', 'confirmed', 'executing']
const joinAnd = (xs: string[], and: string) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} ${and} ${xs[xs.length - 1]}`)
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

function ProposalRow({ p, onDone }: { p: Proposal; onDone: () => void }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  useTick()
  const pending = p.status === 'pending_acceptance'
  const left = pending && p.expires_at ? Math.max(0, Math.round((new Date(p.expires_at).getTime() - nowMs()) / 1000)) : null

  async function run(action: 'hold' | 'accept' | 'reject') {
    setBusy(action); setError(null); setOk(null)
    try { await api.act(p, action); setOk(t(`cf.ok.${action}`)) }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setBusy(null); onDone() } // luôn tải lại: version/trạng thái có thể đã đổi
  }
  const a = p.my_actions
  const entries = Object.entries(p.parties)
  const waiting = entries.filter(([, v]) => !v.accepted).map(([k]) => t(`party.${k}`))
  const settled = ['confirmed', 'executing', 'completed'].includes(p.status)

  return (
    <article className="card stack" aria-label={`${p.shipment.code} ${p.vehicle.plate}`}>
      <div className="spread">
        <div><b>{p.shipment.code}</b> <span className="muted">→</span> <b className="mono">{p.vehicle.plate}</b></div>
        {p.slot && <Chip title={t('cf.srcTip', { src: p.slot.source })}>{p.slot.node_org_name} · {fmtTime(p.slot.start_at)}–{fmtTime(p.slot.end_at).slice(-5)}</Chip>}
      </div>
      <ul className="parties" aria-label={t('rec.parties')}>
        {entries.map(([k, v]) => (
          <li key={k} className={v.accepted ? 'done' : ''}>
            <span className="pa" aria-hidden>{(v.org_name ?? t(`party.${k}`)).charAt(0).toUpperCase()}</span>
            <span className="grow"><b>{t(`party.${k}`)}</b>{v.org_name && <span className="muted"> · {v.org_name}</span>}</span>
            <span className={v.accepted ? 'st ok' : 'st'}>{v.accepted ? `✓ ${t('cf.state.done')}` : pending ? t('cf.state.wait') : settled ? '' : t('cf.state.idle')}</span>
          </li>))}
      </ul>
      {pending && left != null && (
        <div>
          <div className="holdbar" aria-hidden><i className={left < 30 ? 'low' : ''} style={{ width: `${Math.min(100, Math.round((left / 120) * 100))}%` }} /></div>
          <div className="spread">
            <b>{left > 0 ? t('cf.waiting', { who: joinAnd(waiting, t('cf.and')) }) : <Chip kind="FAIL">{t('cf.holdExpired')}</Chip>}</b>
            {left > 0 && <b className={left < 30 ? 'countdown low' : 'countdown'} role="timer">{t('cf.left', { t: mmss(left) })}</b>}
          </div>
        </div>)}
      {settled && <div className="ok-line">{t('cf.confirmedAll')}</div>}
      {p.status === 'proposed' && <div className="muted small">{a.hold ? t('cf.holdHint') : t('cf.waitHolder')}</div>}
      {error && <ErrorNote error={error} />}
      {ok && !settled && <Note kind="ok">{ok}</Note>}
      <div className="row">
        {a.hold && <button className="btn primary" disabled={!!busy} onClick={() => run('hold')}>{t('cf.hold')}</button>}
        {a.accept && <button className="btn primary" disabled={!!busy} onClick={() => run('accept')}>{t('cf.accept')}</button>}
        {a.reject && <button className="btn linkdanger" disabled={!!busy} onClick={() => run('reject')}>{t('cf.reject')}</button>}
        {pending && !a.accept && left != null && left > 0 && <span className="footnote">{t('cf.youWait')}</span>}
        {settled && <a className="btn sm primary" href={`#/tracking?p=${p.id}`}>{t('cf.track')}</a>}
        {settled && <a className="btn sm" href={`#/timeline?p=${p.id}`}>{t('nav.timeline')}</a>}
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
  const live = list.filter((p) => LIVE.includes(p.status))
  const unheld = list.filter((p) => p.status === 'proposed') // chưa giữ chỗ: việc của màn Ghép, gom lại cho gọn
  const past = list.filter((p) => !live.includes(p) && p.status !== 'proposed')
  const refresh = () => { void props.reload(true); void slots.reload(true) }

  return (
    <>
      <div className="card-h"><h1>{t('cf.title')}</h1><span className="live" role="status"><i aria-hidden />{t('cf.live')}</span></div>
      {props.error && <ErrorNote error={props.error} />}
      {props.loading && !props.data ? <Loading /> : list.length === 0 ? <div className="card empty">{t('cf.empty')}</div> : (
        <>
          {live.length === 0 && <div className="card empty">{t('cf.noLive')}</div>}
          <div className="grid2">{live.map((p) => <ProposalRow key={p.id} p={p} onDone={refresh} />)}</div>
          {unheld.length > 0 && <More label={t('cf.unheld', { n: unheld.length })}><div className="grid2">{unheld.map((p) => <ProposalRow key={p.id} p={p} onDone={refresh} />)}</div></More>}
          {past.length > 0 && <More label={t('cf.past', { n: past.length })}><div className="grid2">{past.map((p) => <ProposalRow key={p.id} p={p} onDone={refresh} />)}</div></More>}
        </>
      )}
      {me?.role === 'node_operator' && (
        <section className="card">
          <div className="card-h"><h2>{t('cf.slotsTitle')}</h2></div>
          <div className="table-wrap"><table>
            <thead><tr><th>{t('col.time')}</th><th>{t('col.left')}</th></tr></thead>
            <tbody>{(slots.data ?? []).filter((s) => s.node_org_id === me.org_id && (ageMinutes(s.end_at) ?? 0) <= 60).map((s) => (
              <tr key={s.id}><td className="nw">{fmtTime(s.start_at)}–{fmtTime(s.end_at).slice(-5)}</td>
                <td><Chip kind={s.remaining === 0 ? 'FAIL' : 'PASS'}>{s.remaining}/{s.capacity}</Chip></td></tr>))}</tbody>
          </table></div>
        </section>)}
    </>
  )
}
