import { useMemo, useState, type FormEvent } from 'react'
import { api, ApiError, type Shipment } from '../api'
import { ErrorNote, Note } from '../components/ui'
import { localInputDefault, localInputToIso } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'

const CAN_CREATE = new Set(['shipper', 'carrier'])

export function Request({ go }: { go: (to: string) => void }) {
  const { t } = useI18n()
  const { me, locations, bump } = useApp()
  const origins = useMemo(() => locations.filter((l) => l.kind === 'industrial_zone'), [locations])
  const dests = useMemo(() => locations.filter((l) => l.kind === 'icd'), [locations])
  const [f, setF] = useState(() => ({
    code: `LOT-${Math.floor(100 + Math.random() * 900)}`, cargo_type: 'dry', weight_kg: '12000', volume_m3: '30',
    origin: '', dest: '', ready: localInputDefault(1), deadline: localInputDefault(4), cutoff: localInputDefault(12),
    price: '', customer: '',
  }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [localErr, setLocalErr] = useState<string | null>(null)
  const [created, setCreated] = useState<Shipment | null>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }))

  const allowed = me ? CAN_CREATE.has(me.role) : false
  const origin = f.origin || origins[0]?.id || ''
  const dest = f.dest || dests[0]?.id || ''

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null); setLocalErr(null); setCreated(null)
    const w = Number(f.weight_kg), v = Number(f.volume_m3)
    if (!f.code.trim() || !f.cargo_type || !(w > 0) || !(v > 0) || !origin || !dest || !f.ready || !f.deadline || !f.cutoff) {
      setLocalErr(t('req.err.required')); return
    }
    if (!(f.ready < f.deadline && f.deadline < f.cutoff)) { setLocalErr(t('req.err.order')); return }
    setBusy(true)
    try {
      const s = await api.createShipment({
        code: f.code.trim(), cargo_type: f.cargo_type, weight_kg: w, volume_m3: v, origin_location_id: origin,
        dest_location_id: dest, ready_at: localInputToIso(f.ready), pickup_deadline: localInputToIso(f.deadline),
        cutoff_at: localInputToIso(f.cutoff), price_vnd: f.price ? Number(f.price) : null, customer_name: f.customer || null,
      })
      setCreated(s); bump()
      setF((x) => ({ ...x, code: `LOT-${Math.floor(100 + Math.random() * 900)}` }))
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'UNKNOWN', String(err)))
    } finally { setBusy(false) }
  }

  return (
    <div className="split">
      <section className="card">
        <div className="card-h"><h1>{t('req.title')}</h1><span className="muted">{t('req.intro')}</span></div>
        {me && !allowed && <Note kind="warn">{t('req.cannot', { role: t(`role.${me.role}`) })}</Note>}
        <form className="form" onSubmit={submit} aria-label={t('req.title')}>
          <label>{t('req.code')}<input value={f.code} onChange={set('code')} disabled={!allowed} required maxLength={40} /></label>
          <label>{t('req.cargo')}
            <select value={f.cargo_type} onChange={set('cargo_type')} disabled={!allowed}>
              <option value="dry">{t('cargo.dry')}</option><option value="cold">{t('cargo.cold')}</option>
            </select>
          </label>
          <label>{t('req.weight')}<input type="number" min="1" step="any" inputMode="decimal" value={f.weight_kg} onChange={set('weight_kg')} disabled={!allowed} required /></label>
          <label>{t('req.volume')}<input type="number" min="1" step="any" inputMode="decimal" value={f.volume_m3} onChange={set('volume_m3')} disabled={!allowed} required /></label>
          <label>{t('req.origin')}
            <select value={origin} onChange={set('origin')} disabled={!allowed}>{origins.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
          </label>
          <label>{t('req.dest')}
            <select value={dest} onChange={set('dest')} disabled={!allowed}>{dests.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
          </label>
          <label>{t('req.ready')}<input type="datetime-local" value={f.ready} onChange={set('ready')} disabled={!allowed} required /></label>
          <label>{t('req.deadline')}<input type="datetime-local" value={f.deadline} onChange={set('deadline')} disabled={!allowed} required /></label>
          <label>{t('req.cutoff')}<input type="datetime-local" value={f.cutoff} onChange={set('cutoff')} disabled={!allowed} required /></label>
          <label>{t('req.price')}<input type="number" min="0" inputMode="numeric" value={f.price} onChange={set('price')} disabled={!allowed} /></label>
          <label className="full">{t('req.customer')}<input value={f.customer} onChange={set('customer')} disabled={!allowed} maxLength={200} /></label>
          <div className="full stack">
            <span className="footnote">{t('req.tz')} {t('req.sensitive')}</span>
            {localErr && <Note kind="err">{localErr}</Note>}
            {error && <ErrorNote error={error} />}
            {created && (
              <Note kind="ok">
                <div className="spread"><span>{t('req.created', { code: created.code })}</span>
                  <button type="button" className="btn primary sm" onClick={() => go(`/recommend?lot=${created.id}`)}>{t('req.findMatch')}</button>
                </div>
              </Note>
            )}
            <div><button className="btn primary" type="submit" disabled={!allowed || busy}>{busy ? t('req.submitting') : t('req.submit')}</button></div>
          </div>
        </form>
      </section>
      <aside className="card stack aside">
        <h2>{t('req.reasonsTitle')}</h2>
        <p className="muted" style={{ margin: 0 }}>{t('req.reasons')}</p>
      </aside>
    </div>
  )
}
