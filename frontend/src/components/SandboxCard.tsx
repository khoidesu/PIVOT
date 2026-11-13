import { useMemo, useState } from 'react'
import { api, ApiError, type SandboxResult } from '../api'
import { fmtNum, fmtVnd } from '../fmt'
import { useI18n, tCode } from '../i18n'
import { useApp } from '../store'
import { useData } from '../useData'
import { Chip, ErrorNote, Hint, Loading, More } from './ui'

const ALTS = ['random', 'nearest', 'first'] as const

/** Biểu đồ phân phối "km tiết kiệm mỗi ca" (xe điểm cao nhất vs chọn ngẫu nhiên) — SVG thuần, không thêm thư viện. */
function Histogram({ values }: { values: number[] }) {
  const bins = useMemo(() => {
    if (!values.length) return null
    const lo = Math.floor(Math.min(...values)), hi = Math.ceil(Math.max(...values)), n = Math.min(14, Math.max(6, hi - lo))
    const w = (hi - lo || 1) / n
    const counts = Array.from({ length: n }, () => 0)
    for (const v of values) counts[Math.min(n - 1, Math.floor((v - lo) / w))]++
    return { lo, hi, w, counts, max: Math.max(...counts) }
  }, [values])
  if (!bins) return null
  const W = 320, H = 84, bw = W / bins.counts.length
  const zero = bins.lo < 0 && bins.hi > 0 ? ((0 - bins.lo) / (bins.hi - bins.lo)) * W : null
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={96} preserveAspectRatio="none" role="img" aria-label="histogram">
        {bins.counts.map((c, i) => {
          const h = (c / bins.max) * H
          const neg = bins.lo + (i + 0.5) * bins.w < 0
          return <rect key={i} x={i * bw + 1} y={H - h} width={bw - 2} height={h} rx={2} fill={neg ? 'var(--fail, #d64545)' : 'var(--accent, #dff24b)'} opacity={0.9} />
        })}
        {zero != null && <line x1={zero} x2={zero} y1={0} y2={H} stroke="currentColor" strokeDasharray="3 3" opacity={0.5} vectorEffect="non-scaling-stroke" />}
      </svg>
      <div className="row muted small" style={{ justifyContent: 'space-between' }}><span>{bins.lo} km</span><span>{bins.hi} km</span></div>
    </div>
  )
}

/** Thẻ "Mô phỏng N ca": lợi ích của việc chọn xe điểm cao nhất so với cách chọn khác. MÔ PHỎNG — tách hẳn khỏi sổ lợi ích thật. */
export function SandboxCard() {
  const { t } = useI18n()
  const { me } = useApp()
  const data = useData(() => api.sandboxLatest())
  const [seed, setSeed] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [fresh, setFresh] = useState<SandboxResult | null>(null)
  const r = fresh ?? data.data

  const run = async () => {
    setBusy(true); setError(null)
    try { setFresh(await api.sandboxRun(r?.meta.n ?? 100, seed === '' ? (r?.meta.seed ?? 42) : Number(seed))) }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setBusy(false) }
  }
  const saving = useMemo(() => (r?.cases ?? []).filter((c) => c.feasible && c.top1 && c.random).map((c) => (c.random!.km - c.top1!.km)), [r])

  if (data.loading && !r) return <section className="card"><Loading /></section>
  if (!r) return data.error ? <ErrorNote error={data.error} /> : null
  const s = r.summary, v = s.vs.random.saving, f = (x: number, d = 1) => fmtNum(Number(x.toFixed(d)))
  return (
    <section className="card stack">
      <div className="card-h">
        <h2>{t('sbx.title', { n: r.meta.n })}</h2>
        <span className="row"><Chip kind="sim">{t('badge.mock')}</Chip><Hint text={t('sbx.note')} /></span>
      </div>
      <p className="muted small">{t('sbx.sub')}</p>
      <div className="grid3">
        <div className="fact"><small>{t('sbx.km')}</small><b style={{ fontSize: 22 }}>{f(v.km.mean)} km</b><small className="muted">[{f(v.km.ci95[0])}; {f(v.km.ci95[1])}]</small></div>
        <div className="fact"><small>{t('sbx.vnd')}</small><b style={{ fontSize: 22 }}>{fmtVnd(Math.round(v.cost_vnd.mean))}</b><small className="muted">{t('sbx.win', { p: Math.round(v.cost_vnd.win_rate * 100) })}</small></div>
        <div className="fact"><small>{t('sbx.min')}</small><b style={{ fontSize: 22 }}>{f(v.min_to_icd.mean)}′</b><small className="muted">[{f(v.min_to_icd.ci95[0])}; {f(v.min_to_icd.ci95[1])}]</small></div>
      </div>
      <div className="row muted small">
        <Chip>{t('sbx.feasible', { a: s.n_feasible, b: s.n_cases })}</Chip>
        <Chip kind="warn" title={t('sbx.gateTip')}>{t('sbx.gate', { p: Math.round(s.invalid_without_gate.first_in_list_rate * 100) })}</Chip>
      </div>
      <div><small className="muted">{t('sbx.hist')}</small><Histogram values={saving} /></div>
      {error && <ErrorNote error={error} />}
      <More label={t('sbx.more')}>
        <div className="stack">
          <div className="table-wrap"><table>
            <thead><tr><th /><th className="num">{t('sbx.km')}</th><th className="num">{t('sbx.vnd')}</th><th className="num">{t('sbx.min')}</th></tr></thead>
            <tbody>{ALTS.map((a) => {
              const x = s.vs[a].saving
              return <tr key={a}><td>{tCode(t, 'sbx.vs.', a)}</td><td className="num">{f(x.km.mean)} <small className="muted">{Math.round(x.km.win_rate * 100)}%</small></td>
                <td className="num">{fmtVnd(Math.round(x.cost_vnd.mean))}</td><td className="num">{f(x.min_to_icd.mean)}′</td></tr>
            })}</tbody>
          </table></div>
          <span className="footnote">{t('sbx.params', { seed: r.meta.seed, v: r.meta.assumption_version, rule: r.meta.rule_version })}</span>
          {me?.role === 'dispatcher' && (
            <div className="row">
              <label className="inline">{t('sbx.seed')} <input type="number" min={0} value={seed} placeholder={String(r.meta.seed)} onChange={(e) => setSeed(e.target.value)} style={{ width: 90 }} /></label>
              <button className="btn sm" disabled={busy} onClick={run}>{busy ? t('common.loading') : t('sbx.run')}</button>
            </div>)}
        </div>
      </More>
    </section>
  )
}
