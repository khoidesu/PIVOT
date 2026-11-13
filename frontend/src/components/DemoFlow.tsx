import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, readAs, type Role } from '../api'
import { baseline, deriveFlow, loginNameFor, MAIN_STEPS, type FlowBaseline, type FlowData, type FlowStep } from '../demoFlow'
import { tCode, useI18n } from '../i18n'
import { gsap, reducedMotion } from '../motion'
import { RETRY_MS } from '../conn'
import { Icon } from './Icon'
import { Chip, QueryNote } from './ui'

const FLOW_KEY = 'pivot.tour.flow' // mốc gốc của luồng đang theo dõi (theo tab)
const POLL_MS = 4000

function load(): FlowBaseline | null {
  try { const raw = sessionStorage.getItem(FLOW_KEY); return raw ? (JSON.parse(raw) as FlowBaseline) : null } catch { return null }
}
function store(b: FlowBaseline | null) {
  try { b ? sessionStorage.setItem(FLOW_KEY, JSON.stringify(b)) : sessionStorage.removeItem(FLOW_KEY) } catch { /* bỏ qua */ }
}

/** Đọc dữ liệu thật bằng token của cửa sổ chủ hàng và suy tiến độ. Chỉ đọc — không bao giờ thao tác thay người dùng. */
export function useDemoFlow(token: string | null, active: boolean) {
  const [base, setBase] = useState<FlowBaseline | null>(load)
  const [data, setData] = useState<FlowData | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const save = (b: FlowBaseline | null) => { store(b); setBase(b) }

  useEffect(() => { setData(null); setError(null) }, [token])
  // Chỉ đọc khi thẻ đang mở hoặc luồng đã bắt đầu mà chưa xong (để hiện số bước trên dock).
  const running = !!base && (!data || deriveFlow(base, data).current !== null)
  const on = active || running
  useEffect(() => {
    if (!token || !on) return
    let stop = false
    const tick = async () => {
      try {
        const r = readAs(token)
        const [shipments, proposals, benefits, exceptions] = await Promise.all([r.shipments(), r.proposals(), r.benefits(), r.exceptions()])
        if (!stop) { setData({ shipments, proposals, benefits: benefits.items, exceptions }); setError(null) }
      } catch (e) { if (!stop) setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    }
    void tick()
    const id = setInterval(tick, error ? RETRY_MS : POLL_MS)
    return () => { stop = true; clearInterval(id) }
  }, [token, on, !!error]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { // lần đầu có dữ liệu → chốt mốc gốc; dữ liệu demo vừa reset (không còn lô nào của mốc cũ) → chốt lại
    if (!data) return
    if (!base || (base.lotIds.length > 0 && !data.shipments.some((s) => base.lotIds.includes(s.id)))) save(baseline(data))
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  const flow = useMemo(() => (data && base ? deriveFlow(base, data) : null), [data, base])
  useEffect(() => { // nhớ lô của luồng để lô mới khác tạo sau không "cướp" tiến độ
    if (flow && base && flow.lotId && flow.lotId !== base.lotId) save({ ...base, lotId: flow.lotId })
  }, [flow?.lotId]) // eslint-disable-line react-hooks/exhaustive-deps

  const restart = () => save(data ? baseline(data) : null)
  /** "Bỏ qua": bỏ luồng đang theo dõi — ngừng đọc API, ẩn bước trên thanh trên; mở lại thẻ thì bắt đầu mốc mới. */
  const stop = () => { save(null); setData(null) }
  return { flow, data, error, restart, stop }
}

type Props = {
  flow: ReturnType<typeof useDemoFlow>
  hasWindows: boolean
  onChain: () => void
  onGo: (role: Role, route: string, org: string | null) => void
  onClose: () => void
}

/** Thẻ "Luồng demo": các bước của luồng lõi, tự tích theo dữ liệu thật; bước hiện tại có nút mở đúng cửa sổ + màn. */
export function DemoFlowPanel({ flow: q, hasWindows, onChain, onGo, onClose }: Props) {
  const { t } = useI18n()
  const list = useRef<HTMLOListElement>(null)
  const prevDone = useRef<Set<string> | null>(null)
  const f = q.flow
  const doneKeys = f ? [...f.steps, f.incident].filter((s) => s.done).map((s) => s.key) : []
  const doneSig = doneKeys.join(',')
  useEffect(() => { // bước vừa xong: dấu tích bật lên nhẹ (bỏ qua khi "giảm chuyển động" hoặc lần hiển thị đầu)
    if (!f) return // chưa có dữ liệu: chưa chốt "đã xong" nào, lần có dữ liệu đầu tiên không tính là "vừa xong"
    const before = prevDone.current
    prevDone.current = new Set(doneKeys)
    if (!before || reducedMotion() || !list.current) return
    const fresh = doneKeys.filter((k) => !before.has(k))
    for (const k of fresh) {
      const dot = list.current.parentElement?.querySelector(`[data-step="${k}"] .ws-flow-dot`)
      if (dot) gsap.fromTo(dot, { scale: 0.4 }, { scale: 1, duration: 0.45, ease: 'back.out(3)' })
    }
  }, [doneSig]) // eslint-disable-line react-hooks/exhaustive-deps

  const n = f ? f.steps.filter((s) => s.done).length : 0
  const routeHint = (s: FlowStep) => tCode(t, 'guide.route.', s.route.split('?')[0])
  // optional = mục "Thử sự cố": có nút làm nhưng không phải "bước hiện tại" của luồng chính (không tô, không aria-current)
  const row = (s: FlowStep, i: number | null, current: boolean, optional = false) => (
    <li key={s.key} data-step={s.key} className={`ws-flow-step${s.done ? ' done' : current && !optional ? ' cur' : ''}`} aria-current={current && !optional ? 'step' : undefined}>
      <span className="ws-flow-dot" aria-hidden>{s.done ? <Icon name="check" size={13} /> : i ?? '•'}</span>
      <div className="ws-flow-body">
        <b>{tCode(t, 'flow.s.', s.key)}</b>
        <span className="ws-flow-roles">
          {current && s.waiting.length > 0 && <span className="muted small">{t('flow.wait')}:</span>}
          {(current && s.waiting.length ? s.waiting : s.roles).map((r) => <Chip key={r}>{t(`role.${r}`)}</Chip>)}
        </span>
        {current && loginNameFor(s.org) && <span className="small">{s.org}</span>}
        {current && <span className="muted small">{routeHint(s)}</span>}
      </div>
      {current && <button className={`btn sm${optional ? '' : ' primary'}`} onClick={() => onGo(s.role, s.route, s.org)}>{t('flow.go')}</button>}
    </li>
  )

  return (
    <section className="ws-appearance-pop ws-flow-pop" role="dialog" aria-label={t('flow.title')}>
      <div className="ws-flow-h">
        <h2>{t('flow.title')}</h2>
        {f && <span className="muted small" aria-label={t('flow.progress', { n, m: MAIN_STEPS.length })}>{n}/{MAIN_STEPS.length}</span>}
        <span className="grow" />
        <button className="btn sm icon" aria-label={t('ws.close')} title={t('ws.close')} onClick={onClose}><Icon name="x" size={14} /></button>
      </div>
      {!hasWindows && <button className="btn primary" onClick={onChain}>{t('ws.chain')}</button>}
      <QueryNote q={{ error: q.error, data: q.data }} />
      {hasWindows && !f && !q.error && <ol className="ws-flow-steps" ref={list}>{row({ key: 'lot', done: false, role: 'shipper', roles: ['shipper'], route: 'request', waiting: [], org: null }, 1, true)}</ol>}
      {f && (
        <>
          <ol className="ws-flow-steps" ref={list}>{f.steps.map((s, i) => row(s, i + 1, s.key === f.current))}</ol>
          {f.current === null && <p className="ws-flow-done">{t('flow.done')}</p>}
          <span className="ws-appearance-label">{t('flow.incident')}</span>
          <ol className="ws-flow-steps">{row(f.incident, null, !f.incident.done, true)}</ol>
        </>)}
      <div className="row">
        <button className="btn sm linkish" onClick={() => { q.stop(); onClose() }}>{t('guide.skip')}</button>
        <span className="grow" />
        <button className="btn sm" onClick={q.restart} disabled={!q.data}>{t('flow.restart')}</button>
      </div>
    </section>
  )
}
