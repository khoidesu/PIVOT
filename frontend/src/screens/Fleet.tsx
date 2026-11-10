import { useState } from 'react'
import { api, ApiError, type Shipment } from '../api'
import { Chip, ErrorNote, Loading, Note } from '../components/ui'
import { ageMinutes, fmtNum, fmtTime, fmtVnd } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const CAN_MATCH = new Set(['shipper', 'carrier', 'dispatcher'])
const CAN_EDIT = new Set(['shipper', 'carrier'])

export function Fleet({ go }: { go: (to: string) => void }) {
  const { t } = useI18n()
  const { me, meta } = useApp()
  const lots = useData(() => api.shipments())
  const vehicles = useData(() => api.vehicles())
  const slots = useData(() => api.slots())
  const staleLimit = meta?.stale_position_minutes ?? 5
  const [askCancel, setAskCancel] = useState<string | null>(null)
  const [showCancelled, setShowCancelled] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const guard = async (fn: () => Promise<void>) => {
    setError(null); setMsg(null)
    try { await fn() } catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
  }
  const cancel = (s: Shipment) => guard(async () => { await api.cancelShipment(s.id); setAskCancel(null); setMsg(t('fleet.cancelled', { code: s.code })); await lots.reload(true) })
  const sendPos = (id: string) => guard(async () => { await api.sendVehicleEvent(id, 'VEHICLE_POSITION'); setMsg(t('fleet.posSent')); setTimeout(() => { void vehicles.reload(true) }, 1600) })
  const ownerOf = (s: Shipment) => !!me && CAN_EDIT.has(me.role) && s.tenant_id === me.org_id
  const visibleLots = (lots.data ?? []).filter((s) => showCancelled || s.status !== 'cancelled')

  const priceCell = (s: Shipment) =>
    s.price_vnd != null ? fmtVnd(s.price_vnd) : me && s.tenant_id !== me.org_id ? <span className="muted small">{t('common.hidden')}</span> : '—'

  return (
    <>
      <section className="card">
        <div className="card-h"><h1>{t('fleet.lots')}</h1><span className="muted">{t('fleet.lotsHint')}</span></div>
        {lots.error && <ErrorNote error={lots.error} />}
        {error && <ErrorNote error={error} />}
        {msg && <Note kind="ok">{msg}</Note>}
        {lots.data?.some((x) => x.status === 'cancelled') && <label className="check small"><input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} />{t('fleet.showCancelled')}</label>}
        {lots.loading && !lots.data ? <Loading /> : visibleLots.length === 0 ? <div className="empty">{t('fleet.empty')}</div> : (
          <div className="table-wrap"><table>
            <thead><tr>
              <th>{t('fleet.col.code')}</th><th>{t('fleet.col.cargo')}</th><th className="num">{t('fleet.col.load')}</th>
              <th>{t('fleet.col.pickup')}</th><th>{t('fleet.col.cutoff')}</th><th>{t('fleet.col.status')}</th><th className="num">{t('fleet.col.price')}</th><th />
            </tr></thead>
            <tbody>{visibleLots.map((s) => (
              <tr key={s.id}>
                <td><b>{s.code}</b>{s.is_simulated && <> <Chip kind="sim">{t('badge.mock')}</Chip></>}</td>
                <td>{t(`cargo.${s.cargo_type}`)}</td>
                <td className="num">{s.weight_kg == null ? '—' : `${fmtNum(s.weight_kg)} kg`}<br /><span className="muted small">{s.volume_m3 == null ? '—' : `${s.volume_m3} m³`}</span></td>
                <td className="nw">{fmtTime(s.pickup_deadline)}</td><td className="nw">{fmtTime(s.cutoff_at)}</td>
                <td>
                  <Chip kind={s.status === 'open' ? 'teal' : s.status === 'completed' ? 'good' : undefined}>{t(`status.${s.status}`)}</Chip>
                  {s.missing_fields.length > 0 && <div><Chip kind="UNKNOWN">{t('fleet.needsData', { fields: s.missing_fields.join(', ') })}</Chip></div>}
                </td>
                <td className="num">{priceCell(s)}</td>
                <td className="nw">
                  {s.status === 'open' && me && CAN_MATCH.has(me.role) && (
                    <button className="btn sm" onClick={() => go(`/recommend?lot=${s.id}`)}>{t('fleet.match')}</button>)}
                  {s.status === 'open' && ownerOf(s) && (askCancel === s.id ? (
                    <div className="stack"><span className="small">{t('fleet.cancelAsk', { code: s.code })}</span>
                      <div className="row"><button className="btn sm danger" onClick={() => cancel(s)}>{t('fleet.cancelYes')}</button>
                        <button className="btn sm" onClick={() => setAskCancel(null)}>{t('fleet.cancelNo')}</button></div></div>
                  ) : (
                    <> <button className="btn sm" onClick={() => go(`/request?edit=${s.id}`)}>{t('fleet.edit')}</button>
                      <button className="btn sm danger" onClick={() => setAskCancel(s.id)}>{t('fleet.cancel')}</button></>))}
                </td>
              </tr>))}</tbody>
          </table></div>
        )}
      </section>

      <div className="grid2">
        <section className="card">
          <div className="card-h"><h2>{t('fleet.vehicles')}</h2><span className="muted">{t('fleet.vehiclesHint', { n: staleLimit })}</span></div>
          {vehicles.error && <ErrorNote error={vehicles.error} />}
          {vehicles.loading && !vehicles.data ? <Loading /> : vehicles.data && vehicles.data.length === 0 ? <div className="empty">{t('fleet.empty')}</div> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t('fleet.col.plate')}</th><th>{t('fleet.col.types')}</th><th className="num">{t('fleet.col.cap')}</th><th>{t('fleet.col.status')}</th><th>{t('fleet.col.pos')}</th><th /></tr></thead>
              <tbody>{vehicles.data?.map((v) => {
                const age = ageMinutes(v.position_updated_at)
                const stale = age == null || age > staleLimit
                return (
                  <tr key={v.id}>
                    <td><b className="mono">{v.plate}</b></td>
                    <td>{v.cargo_types.map((c) => t(`cargo.${c}`)).join(', ')}</td>
                    <td className="num">{fmtNum(v.capacity_kg)} kg<br /><span className="muted small">{v.capacity_m3} m³</span></td>
                    <td><Chip kind={v.status === 'available' ? 'good' : v.status === 'offline' ? 'bad' : 'warn'}>{t(`status.${v.status}`)}</Chip></td>
                    <td>{age == null ? '—' : t(age === 0 ? 'common.justNow' : 'common.ago', { n: age })} {stale && <Chip kind="FAIL">DATA_STALE</Chip>}</td>
                    <td>{me?.role === 'carrier' && v.tenant_id === me.org_id && <button className="btn sm" onClick={() => sendPos(v.id)}>{t('fleet.updatePos')}</button>}</td>
                  </tr>)
              })}</tbody>
            </table></div>
          )}
        </section>

        <section className="card">
          <div className="card-h"><h2>{t('fleet.slots')}</h2><Chip kind="sim">{t('badge.mock')}</Chip></div>
          {slots.error && <ErrorNote error={slots.error} />}
          {slots.loading && !slots.data ? <Loading /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t('fleet.slotCol.time')}</th><th>{t('fleet.slotCol.left')}</th><th>{t('fleet.slotCol.source')}</th></tr></thead>
              <tbody>{slots.data?.map((s) => (
                <tr key={s.id}>
                  <td className="nw">{fmtTime(s.start_at)}–{fmtTime(s.end_at).slice(-5)}</td>
                  <td><Chip kind={s.remaining === 0 ? 'FAIL' : 'PASS'}>{s.remaining}/{s.capacity}</Chip></td>
                  <td><Chip kind="sim">{s.source}</Chip></td>
                </tr>))}</tbody>
            </table></div>
          )}
          <p className="footnote">{t('cf.src.mock')}</p>
        </section>
      </div>
      {me && !CAN_MATCH.has(me.role) && <Note kind="info">{t('rec.cannot', { role: t(`role.${me.role}`) })}</Note>}
    </>
  )
}
