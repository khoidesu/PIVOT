import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { api, ApiError, type IntakeDraft, type Shipment } from '../api'
import { Chip, ErrorNote, Hint, Note } from '../components/ui'
import { Icon } from '../components/Icon'
import { IntakeTile } from '../components/IntakeTile'
import { ACCEPT, prepareImage } from '../image'
import { isoToLocalInput, localInputDefault, localInputToIso } from '../fmt'
import { useI18n } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'

const CAN_CREATE = new Set(['shipper', 'carrier'])
// trường của bản nháp → trường của form (để đánh dấu "cần xem lại")
const FORM_FIELD: Record<string, string> = { cargo_type: 'cargo_type', weight_kg: 'weight_kg', volume_m3: 'volume_m3', origin: 'origin', dest: 'dest', ready_at: 'ready', pickup_deadline: 'deadline', cutoff_at: 'cutoff' }
const DRAFT_ORDER = ['cargo_type', 'weight_kg', 'volume_m3', 'origin', 'dest', 'ready_at', 'pickup_deadline', 'cutoff_at', 'price_vnd', 'customer_name'] as const

const newCode = () => `LOT-${Math.floor(100 + Math.random() * 900)}`
const blank = () => ({
  code: newCode(), cargo_type: 'dry', weight_kg: '12000', volume_m3: '30', origin: '', dest: '',
  ready: localInputDefault(1), deadline: localInputDefault(4), cutoff: localInputDefault(12), price: '', customer: '',
})

export function Request({ go, query }: { go: (to: string) => void; query: URLSearchParams }) {
  const { t } = useI18n()
  const { me, meta, locations, bump } = useApp()
  const editId = query.get('edit')
  const origins = useMemo(() => locations.filter((l) => l.kind === 'industrial_zone'), [locations])
  const dests = useMemo(() => locations.filter((l) => l.kind === 'icd'), [locations])
  const [f, setF] = useState(blank)
  const [editing, setEditing] = useState<Shipment | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [localErr, setLocalErr] = useState<string | null>(null)
  const [done, setDone] = useState<{ shipment: Shipment; edited: boolean } | null>(null)
  // nhập liệu từ văn bản (thu gọn mặc định)
  const [showImport, setShowImport] = useState(false)
  const [text, setText] = useState('')
  const [draft, setDraft] = useState<IntakeDraft | null>(null)
  const [drafting, setDrafting] = useState(false)
  const [reading, setReading] = useState(false) // đang đọc ảnh
  const [reviewed, setReviewed] = useState(false)
  const [draftUsed, setDraftUsed] = useState(false)
  const [imgUrl, setImgUrl] = useState<string | null>(null) // ảnh xem trước (nếu bản nháp đến từ ảnh)
  const fileRef = useRef<HTMLInputElement>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }))

  const lots = useData(() => api.shipments())
  useEffect(() => { // chế độ sửa: nạp dữ liệu lô vào form
    if (!editId) { setEditing(null); return }
    const s = lots.data?.find((x) => x.id === editId)
    if (!s) return
    setEditing(s)
    setF({
      code: s.code, cargo_type: s.cargo_type, weight_kg: s.weight_kg == null ? '' : String(s.weight_kg), volume_m3: s.volume_m3 == null ? '' : String(s.volume_m3),
      origin: s.origin_location_id, dest: s.dest_location_id, ready: isoToLocalInput(s.ready_at),
      deadline: s.pickup_deadline ? isoToLocalInput(s.pickup_deadline) : '', cutoff: s.cutoff_at ? isoToLocalInput(s.cutoff_at) : '',
      price: '', customer: '',
    })
  }, [editId, lots.data])

  const allowed = me ? CAN_CREATE.has(me.role) : false
  const origin = f.origin || (draftUsed ? '' : origins[0]?.id || '') // bản nháp thiếu điểm → để trống, không tự chọn hộ
  const dest = f.dest || (draftUsed ? '' : dests[0]?.id || '')
  const reviewFields = new Set(draftUsed && draft ? draft.needs_review.map((k) => FORM_FIELD[k]).filter(Boolean) : [])
  const mustConfirm = draftUsed && !!draft && draft.needs_review.length > 0 && !reviewed
  const cls = (name: string) => (reviewFields.has(name) ? 'review' : undefined)

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // cho phép chọn lại cùng một tệp
    if (!file) return
    setDrafting(true); setReading(true); setError(null); setDraft(null); setDraftUsed(false); setReviewed(false)
    try {
      const img = await prepareImage(file)
      if (imgUrl) URL.revokeObjectURL(imgUrl)
      setImgUrl(img.previewUrl)
      const d = await api.intakeImage(img.base64)
      setDraft(d); applyDraft(d) // tải ảnh xong là điền thẳng vào form (người dùng chỉ còn xem lại + xác nhận), không cần bấm thêm
    } catch (err) {
      setImgUrl(null)
      setError(err instanceof ApiError ? err : new ApiError(0, 'IMAGE_LOCAL', t((err as Error).message === 'TOO_LARGE' ? 'err.IMAGE_TOO_LARGE' : 'err.UNSUPPORTED_IMAGE')))
    } finally { setDrafting(false); setReading(false) }
  }
  async function extract() {
    setDrafting(true); setError(null); setDraft(null); setDraftUsed(false); setReviewed(false); setImgUrl(null)
    try { setDraft(await api.intakeDraft(text)) }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setDrafting(false) }
  }
  function applyDraft(d: IntakeDraft) {
    const v = (k: string) => d.fields[k]?.value
    setF((x) => ({
      ...x,
      cargo_type: (v('cargo_type') as string) ?? '',
      weight_kg: v('weight_kg') != null ? String(v('weight_kg')) : '', volume_m3: v('volume_m3') != null ? String(v('volume_m3')) : '',
      origin: (v('origin') as string) ?? '', dest: (v('dest') as string) ?? '',
      ready: v('ready_at') ? isoToLocalInput(v('ready_at') as string) : '',
      deadline: v('pickup_deadline') ? isoToLocalInput(v('pickup_deadline') as string) : '',
      cutoff: v('cutoff_at') ? isoToLocalInput(v('cutoff_at') as string) : '',
      price: v('price_vnd') != null ? String(v('price_vnd')) : '', customer: (v('customer_name') as string) ?? '',
    }))
    setDraftUsed(true); setReviewed(false); setDone(null); setShowImport(false)
  }
  const useDraft = () => { if (draft) applyDraft(draft) }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null); setLocalErr(null); setDone(null)
    const w = Number(f.weight_kg), v = Number(f.volume_m3)
    if (!f.code.trim() || !f.cargo_type || !(w > 0) || !(v > 0) || !origin || !dest || !f.ready || !f.deadline || !f.cutoff) { setLocalErr(t('req.err.required')); return }
    if (!(f.ready < f.deadline && f.deadline < f.cutoff)) { setLocalErr(t('req.err.order')); return }
    if (mustConfirm) { setLocalErr(t('in.mustConfirm')); return }
    setBusy(true)
    try {
      const body = {
        cargo_type: f.cargo_type, weight_kg: w, volume_m3: v, origin_location_id: origin, dest_location_id: dest,
        ready_at: localInputToIso(f.ready), pickup_deadline: localInputToIso(f.deadline), cutoff_at: localInputToIso(f.cutoff),
        price_vnd: f.price ? Number(f.price) : null, customer_name: f.customer || null,
      }
      if (editing) {
        const s = await api.updateShipment(editing.id, { version: editing.version, ...body })
        setDone({ shipment: s, edited: true }); setEditing(s); await lots.reload(true); bump()
      } else {
        const s = await api.createShipment({ code: f.code.trim(), ...body, draft_id: draftUsed ? draft?.draft_id : null })
        setDone({ shipment: s, edited: false }); bump()
        setF(blank()); setDraft(null); setDraftUsed(false); setText(''); setReviewed(false)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'UNKNOWN', String(err)))
      if (err instanceof ApiError && err.code === 'VERSION_CONFLICT') void lots.reload(true)
    } finally { setBusy(false) }
  }

  const notFound = !!editId && !!lots.data && !lots.data.find((x) => x.id === editId)

  return (
    <div style={{ maxWidth: 900, width: '100%', margin: '0 auto' }} className="stack">
      <section className="card">
        <div className="card-h">
          <h1>{editing ? t('req.edit', { code: editing.code }) : t('req.new')}</h1>
        </div>
        {!editing && allowed && (
          <div className="tiles">
            <IntakeTile icon="message" title={t('req.paste')} sub={t('req.paste.sub')} active={showImport} onClick={() => setShowImport((v) => !v)} />
            {meta?.image_intake_enabled && (
              <IntakeTile icon="image" index={1} title={reading ? t('in.img.reading') : t('req.photo')} sub={t('req.photo.sub')} busy={reading} disabled={drafting} onClick={() => fileRef.current?.click()} />)}
            <input ref={fileRef} type="file" accept={ACCEPT} className="sr" tabIndex={-1} aria-hidden onChange={onFile} />
          </div>)}
        {me && !allowed && <Note kind="warn">{t('req.cannot')}</Note>}
        {notFound && <Note kind="err">{t('req.notFound')}</Note>}

        {showImport && !editing && allowed && (
          <div className="stack import">
            <label className="sr" htmlFor="intake-text">{t('req.paste')}</label>
            <textarea id="intake-text" value={text} onChange={(e) => setText(e.target.value)} placeholder={t('in.placeholder')} maxLength={8000} rows={3} />
            <div className="row">
              <button type="button" className="btn sm" onClick={extract} disabled={drafting || !text.trim()}>{drafting ? t('in.running') : t('in.run')}</button>
              {(draft || text) && <button type="button" className="btn sm" onClick={() => { setText(''); setDraft(null); setDraftUsed(false); setImgUrl(null) }}>{t('in.clear')}</button>}
            </div>
            {draft && (
              <div className="stack">
                <div className="row"><Chip kind={draft.extractor.kind === 'llm' ? 'teal' : 'warn'}>{t('in.draft', { by: draft.extractor.kind === 'llm' ? t('in.byLlm', { name: draft.extractor.name }) : t('in.byRule') })}</Chip></div>
                {draft.image_quota_remaining != null && <span className="footnote">{t('in.img.left', { n: draft.image_quota_remaining })}</span>}
                {draft.suspicious_instructions && <Note kind="err">{t('in.suspicious')}</Note>}
                {draft.looks_like_request === false && <Note kind="warn">{t('in.notRequest')}</Note>}
                {draft.multiple_shipments && <Note kind="warn">{t('in.multi')}</Note>}
                {draft.extractor.note && <Note kind="warn">{t(`in.llm.${draft.extractor.note}`)}</Note>}
                {imgUrl && draft.transcript && (
                  <div className="img-pair">
                    <img src={imgUrl} alt={t('in.img.alt')} />
                    <pre className="transcript" aria-label={t('in.img.text')}>{draft.transcript}</pre>
                  </div>)}
                {(() => {
                  const gaps = DRAFT_ORDER.filter((k) => k !== 'price_vnd' && k !== 'customer_name' && draft.fields[k]?.value == null)
                  return gaps.length > 0 && <Note kind="warn">{t('in.gaps', { list: gaps.map((k) => t(`in.f.${k}`)).join(', ') })}</Note>
                })()}
                <div className="table-wrap"><table>
                  <thead><tr><th>{t('in.col.field')}</th><th>{t('in.col.value')}</th><th>{t('in.col.source')}</th><th /></tr></thead>
                  <tbody>{DRAFT_ORDER.map((k) => {
                    const x = draft.fields[k]
                    if (!x) return null
                    const optionalGap = x.value == null && (k === 'price_vnd' || k === 'customer_name') // tuỳ chọn: vẫn hiện dòng để người dùng thấy tin không nêu, nhưng không báo động
                    const warn = x.status !== 'ok' && !optionalGap
                    return (
                      <tr key={k}>
                        <td><b>{t(`in.f.${k}`)}</b></td>
                        <td>{x.value == null ? <span className="muted">—</span> : x.display}</td>
                        <td>{x.source ? <q className="small">{x.source.quote}</q> : <span className="muted small">{t('in.missing')}</span>}</td>
                        <td>{warn
                          ? <Chip kind="UNKNOWN" title={x.notes.filter((n) => !n.startsWith('candidates')).map((n) => (t(`in.note.${n}`) === `in.note.${n}` ? n : t(`in.note.${n}`))).join(' ')}><Icon name="alert" size={13} /></Chip>
                          : optionalGap ? <span className="muted small">—</span> : <Chip kind="PASS">✓</Chip>}
                          {warn && x.notes.filter((n) => !n.startsWith('candidates')).map((n) => <div key={n} className="footnote">{t(`in.note.${n}`) === `in.note.${n}` ? n : t(`in.note.${n}`)}</div>)}</td>
                      </tr>)
                  })}</tbody>
                </table></div>
                <div><button type="button" className="btn primary sm" onClick={useDraft}>{t('in.use')}</button></div>
              </div>)}
          </div>)}

        {reading && <Note kind="info">{t('in.img.reading')}</Note>}
        {draftUsed && imgUrl && draft?.transcript && (
          <div className="stack import">
            <div className="row">
              <Chip kind="teal">{t('in.img.filled')}</Chip>
              {draft.image_quota_remaining != null && <span className="footnote">{t('in.img.left', { n: draft.image_quota_remaining })}</span>}
              {draft.suspicious_instructions && <Chip kind="bad">{t('in.suspicious')}</Chip>}
            </div>
            <div className="img-pair">
              <img src={imgUrl} alt={t('in.img.alt')} />
              <pre className="transcript" aria-label={t('in.img.text')}>{draft.transcript}</pre>
            </div>
          </div>)}

        <form className="form" onSubmit={submit} aria-label={t('req.new')}>
          <label>{t('req.code')}<input value={f.code} onChange={set('code')} disabled={!allowed || !!editing} required maxLength={40} title={editing ? t('req.codeLocked') : undefined} /></label>
          <label className={cls('cargo_type')}>{t('req.cargo')}
            <select value={f.cargo_type} onChange={set('cargo_type')} disabled={!allowed} required>
              {!f.cargo_type && <option value="">{t('req.pick')}</option>}
              <option value="dry">{t('cargo.dry')}</option><option value="cold">{t('cargo.cold')}</option>
            </select>
          </label>
          <label className={cls('weight_kg')}>{t('req.weight')}<input type="number" min="1" step="any" inputMode="decimal" value={f.weight_kg} onChange={set('weight_kg')} disabled={!allowed} required /></label>
          <label className={cls('volume_m3')}>{t('req.volume')}<input type="number" min="1" step="any" inputMode="decimal" value={f.volume_m3} onChange={set('volume_m3')} disabled={!allowed} required /></label>
          <label className={cls('origin')}>{t('req.origin')}
            <select value={origin} onChange={set('origin')} disabled={!allowed} required>{!origin && <option value="">{t('req.pick')}</option>}{origins.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
          </label>
          <label className={cls('dest')}>{t('req.dest')}
            <select value={dest} onChange={set('dest')} disabled={!allowed} required>{!dest && <option value="">{t('req.pick')}</option>}{dests.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
          </label>
          <label className={cls('ready')}>{t('req.ready')}<input type="datetime-local" value={f.ready} onChange={set('ready')} disabled={!allowed} required /></label>
          <label className={cls('deadline')}>{t('req.deadline')}<input type="datetime-local" value={f.deadline} onChange={set('deadline')} disabled={!allowed} required /></label>
          <label className={cls('cutoff')}>{t('req.cutoff')}<input type="datetime-local" value={f.cutoff} onChange={set('cutoff')} disabled={!allowed} required /></label>
          <label>{t('req.price')} <Hint text={t('req.privacyTip')} /><input type="number" min="0" inputMode="numeric" value={f.price} onChange={set('price')} disabled={!allowed} /></label>
          <label className="full">{t('req.customer')}<input value={f.customer} onChange={set('customer')} disabled={!allowed} maxLength={200} /></label>
          <div className="full stack">
            {draftUsed && draft && draft.needs_review.length > 0 && (
              <label className="check"><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />{t('in.confirm')}</label>)}
            {localErr && <Note kind="err">{localErr}</Note>}
            {error && <ErrorNote error={error} />}
            {done && (
              <Note kind="ok">
                <div className="spread"><span>{done.edited ? t('req.updated', { code: done.shipment.code }) : t('req.created', { code: done.shipment.code })}</span>
                  <button type="button" className="btn primary sm" onClick={() => go(`/recommend?lot=${done.shipment.id}`)}>{t('req.match')}</button></div>
              </Note>)}
            <div className="row">
              <button className="btn primary" type="submit" disabled={!allowed || busy || notFound}>{busy ? t('req.submitting') : editing ? t('req.update') : t('req.submit')}</button>
              {editing && <button type="button" className="btn" onClick={() => go('/fleet')}>{t('req.back')}</button>}
            </div>
          </div>
        </form>
      </section>
    </div>
  )
}
