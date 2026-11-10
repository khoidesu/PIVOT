import { useState } from 'react'
import { api, ApiError, SCENARIO_IDS, type ScenarioResult } from '../api'
import { Chip, ErrorNote, Note } from '../components/ui'
import { useI18n } from '../i18n'
import { useApp } from '../store'

export function Demo() {
  const { t } = useI18n()
  const { me, bump } = useApp()
  const [res, setRes] = useState<Record<string, ScenarioResult>>({})
  const [running, setRunning] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const allowed = me?.role === 'dispatcher'

  async function run(id: string) {
    setRunning(id); setError(null)
    try { setRes((r) => ({ ...r, [id]: undefined as never })); const out = await api.runScenario(id); setRes((r) => ({ ...r, [id]: out })); bump() }
    catch (e) { setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) }
    finally { setRunning(null) }
  }
  async function runAll() { for (const id of SCENARIO_IDS) await run(id) }
  const passed = SCENARIO_IDS.filter((id) => res[id]?.passed).length

  return (
    <>
      <section className="card stack">
        <div className="card-h"><h1>{t('demo.title')}</h1><Chip kind="sim">{t('badge.mock')}</Chip></div>
        <span className="muted">{t('demo.intro')}</span>
        {!allowed && <Note kind="warn">{t('demo.only')}</Note>}
        <div className="row">
          <button className="btn primary" disabled={!allowed || !!running} onClick={runAll}>{running ? t('demo.running') : t('demo.runAll')}</button>
          {Object.keys(res).length > 0 && <Chip kind={passed === SCENARIO_IDS.length ? 'good' : 'warn'}>{t('demo.all', { n: passed })}</Chip>}
        </div>
      </section>
      {error && <ErrorNote error={error} />}
      <div className="grid2">
        {SCENARIO_IDS.map((id) => {
          const r = res[id]
          return (
            <article key={id} className="card stack">
              <div className="spread">
                <h2>{t(`demo.s.${id}.title`)}</h2>
                {r && <Chip kind={r.passed ? 'PASS' : 'FAIL'}>{r.passed ? t('demo.pass') : t('demo.fail')}</Chip>}
              </div>
              <span className="muted small">{t(`demo.s.${id}.desc`)}</span>
              <div><button className="btn sm" disabled={!allowed || !!running} onClick={() => run(id)}>{running === id ? t('demo.running') : t('demo.run')}</button></div>
              {r && (
                <>
                  <ul className="why" style={{ listStyle: 'none', paddingLeft: 0 }}>
                    {r.steps.map((s, i) => (
                      <li key={i}><Chip kind={s.ok ? 'PASS' : 'FAIL'}>{s.ok ? '✓' : '✗'}</Chip> {s.label}{s.detail && <span className="muted small"> — {s.detail}</span>}</li>))}
                  </ul>
                  {r.open && <a href={r.open} className="small">{t('demo.open')}</a>}
                </>)}
            </article>)
        })}
      </div>
    </>
  )
}
