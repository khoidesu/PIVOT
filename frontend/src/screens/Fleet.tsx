import { useState } from 'react'
import { api, ApiError, type Shipment } from '../api'
import { Chip, ErrorNote, Loading, Note } from '../components/ui'
import { Icon } from '../components/Icon'
import { ageMinutes, fmtNum, fmtTime, fmtVnd } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

type Tab = 'lots' | 'vehicles' | 'slots'
const CAN_MATCH = new Set(['shipper', 'carrier', 'dispatcher'])
const CAN_EDIT = new Set(['shipper', 'carrier'])
const firstTab = (role?: string): Tab => (role === 'carrier' ? 'vehicles' : role === 'node_operator' ? 'slots' : 'lots') // mặc định theo vai trò

export function Fleet({ go }: { go: (to: string) => void }) {
  const { t } = useI18n()
  const { me, meta } = useApp()
  const lots = useData(() => api.shipments())
  const vehicles = useData(() => api.vehicles())
  const slots = useData(() => api.slots())
  const [tab, setTab] = useState<Tab>(firstTab(me?.role))
  const [askCancel, setAskCancel] = useState<string | null>(null)
  const [showCancelled, setShowCancelled] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const staleLimit = meta?.stale_position_minutes ?? 5
  const canEdit = !!me && CAN_EDIT.has(me.role)

  const guard = async (fn: () => Promise<void>) => {
    setError(null); setMsg(null)
    try { await fn() } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
  }
  const cancel = (s: Shipment) => guard(async () => { await api.cancelShipment(s.id); setAskCancel(null); setMsg(t('fleet.cancelled', { code: s.code })); await lots.reload(true) })
  const mine = (vehicles.data ?? []).filter((v) => !!me && v.tenant_id === me.org_id)
  const sendAll = () => guard(async () => {
    for (const v of mine) await api.sendVehicleEvent(v.id, 'VEHICLE_POSITION')
    setMsg(t('fleet.updateAllDone', { n: mine.length })); setTimeout(() => { void vehicles.reload(true) }, 1600)
  })
  const myOpen = (lots.data ?? []).filter((s) => s.status === 'open' && !!me && s.tenant_id === me.org_id)
  const refreshAll = () => guard(async () => {
    for (const s of myOpen) await api.refreshShipment(s.id)
    setMsg(t('fleet.refreshDone', { n: myOpen.length })); await lots.reload(true)
  })
  const ownerOf = (s: Shipment) => canEdit && s.tenant_id === me?.org_id
  const visibleLots = (lots.data ?? []).filter((s) => showCancelled || s.status !== 'cancelled')
  const cur = tab === 'lots' ? lots : tab === 'vehicles' ? vehicles : slots

  return (
    <section className="card stack">
      <div className="card-h">
        <h1>{t(`nav.fleet.${me?.role ?? 'shipper'}`)}</h1>
        <div className="row">
          <div className="seg" role="tablist">
            {(['lots', 'vehicles', 'slots'] as Tab[]).map((x) => (
              <button key={x} role="tab" aria-selected={tab === x} aria-pressed={tab === x} onClick={() => setTab(x)}>{t(`fleet.tab.${x}`)}</button>))}
          </div>
          {canEdit && <button className="btn sm primary" onClick={() => go('/request')}>{t('fleet.add')}</button>}
          {tab === 'lots' && me?.role === 'shipper' && myOpen.length > 0 && <button className="btn sm" title={t('fleet.refreshAllTip')} onClick={refreshAll}>{t('fleet.refreshAll')}</button>}
          {tab === 'vehicles' && me?.role === 'carrier' && mine.length > 0 && <button className="btn sm" onClick={sendAll}>{t('fleet.updateAll')}</button>}
        </div>
      </div>
      {error && <ErrorNote error={error} />}
      {msg && <Note kind="ok">{msg}</Note>}
      {cur.error && <ErrorNote error={cur.error} />}
      {cur.loading && !cur.data ? <Loading /> : tab === 'lots' ? (
        <>
          {lots.data?.some((x) => x.status === 'cancelled') && <label className="check small"><input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} />{t('fleet.showCancelled')}</label>}
          {visibleLots.length === 0 ? <div className="empty">{t('fleet.empty')}</div> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t('col.lot')}</th><th className="num">{t('col.load')}</th><th>{t('col.due')}</th>{canEdit && <th className="num">{t('col.price')}</th>}<th>{t('col.status')}</th><th /></tr></thead>
              <tbody>{visibleLots.map((s) => (
                <tr key={s.id}>
                  <td><b>{s.code}</b><div className="muted small">{t(`cargo.${s.cargo_type}`)}</div></td>
                  <td className="num">{s.weight_kg == null ? '—' : `${fmtNum(s.weight_kg)} kg`}<div className="muted small">{s.volume_m3 == null ? '—' : `${s.volume_m3} m³`}</div></td>
                  <td className="nw">{fmtTime(s.pickup_deadline)}<div className="muted small">{fmtTime(s.cutoff_at)}</div></td>
                  {canEdit && <td className="num">{s.price_vnd != null ? fmtVnd(s.price_vnd) : '—'}</td>}
                  <td>
                    <Chip kind={s.status === 'open' ? 'teal' : s.status === 'completed' ? 'good' : undefined}>{t(`status.${s.status}`)}</Chip>
                    {s.missing_fields.length > 0 && <div><Chip kind="UNKNOWN" title={t('fleet.needsTip', { fields: s.missing_fields.join(', ') })}>{t('fleet.needs')}</Chip></div>}
                  </td>
                  <td className="nw">
                    {s.status === 'open' && me && CAN_MATCH.has(me.role) && (
                      <button className="btn sm icon" aria-label={t('fleet.match')} title={t('fleet.match')} onClick={() => go(`/recommend?lot=${s.id}`)}><Icon name="play" size={14} /></button>)}
                    {s.status === 'open' && ownerOf(s) && (askCancel === s.id ? (
                      <span className="stack"><span className="small">{t('fleet.cancelAsk', { code: s.code })}</span>
                        <span className="row"><button className="btn sm danger" onClick={() => cancel(s)}>{t('fleet.cancelYes')}</button>
                          <button className="btn sm" onClick={() => setAskCancel(null)}>{t('fleet.cancelNo')}</button></span></span>
                    ) : (
                      <> <button className="btn sm icon" aria-label={t('fleet.edit')} title={t('fleet.edit')} onClick={() => go(`/request?edit=${s.id}`)}><Icon name="pencil" size={14} /></button>
                        <button className="btn sm icon danger" aria-label={t('fleet.cancel')} title={t('fleet.cancel')} onClick={() => setAskCancel(s.id)}><Icon name="x" size={14} /></button></>))}
                  </td>
                </tr>))}</tbody>
            </table></div>)}
        </>
      ) : tab === 'vehicles' ? (
        (vehicles.data ?? []).length === 0 ? <div className="empty">{t('fleet.empty')}</div> : (
          <div className="table-wrap"><table>
            <thead><tr><th>{t('col.plate')}</th><th className="num">{t('col.cap')}</th><th>{t('col.status')}</th><th>{t('col.pos')}</th></tr></thead>
            <tbody>{vehicles.data?.map((v) => {
              const age = ageMinutes(v.position_updated_at)
              const stale = age == null || age > staleLimit
              return (
                <tr key={v.id}>
                  <td><b className="mono">{v.plate}</b></td>
                  <td className="num">{fmtNum(v.capacity_kg)} kg<div className="muted small">{v.capacity_m3} m³</div></td>
                  <td><Chip kind={v.status === 'available' ? 'good' : v.status === 'offline' ? 'bad' : 'warn'}>{t(`status.${v.status}`)}</Chip></td>
                  <td>{age == null ? '—' : t(age === 0 ? 'common.justNow' : 'common.ago', { n: age })} {stale && <Chip kind="FAIL" title={t('fleet.staleTip', { n: staleLimit })}>{t('fleet.stale')}</Chip>}</td>
                </tr>)
            })}</tbody>
          </table></div>)
      ) : (
        (slots.data ?? []).length === 0 ? <div className="empty">{t('fleet.empty')}</div> : (
          <div className="table-wrap"><table>
            <thead><tr><th>{t('col.time')}</th><th>{t('col.left')}</th></tr></thead>
            <tbody>{slots.data?.map((s) => (
              <tr key={s.id}>
                <td className="nw">{fmtTime(s.start_at)}–{fmtTime(s.end_at).slice(-5)}</td>
                <td><Chip kind={s.remaining === 0 ? 'FAIL' : 'PASS'} title={t('cf.srcTip', { src: s.source })}>{s.remaining}/{s.capacity}</Chip></td>
              </tr>))}</tbody>
          </table></div>)
      )}
    </section>
  )
}
