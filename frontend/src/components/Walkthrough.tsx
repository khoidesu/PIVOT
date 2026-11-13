import { useEffect, useState } from 'react'
import { Icon } from './Icon'
import { useI18n } from '../i18n'

export type WalkthroughStep = { target: string; title: string; body: string }

type Rect = { x: number; y: number; width: number; height: number }

/** Tour có vùng tương tác quanh mục đang giải thích để người dùng thử nút thật ngay trong lúc xem. */
export function Walkthrough({ steps, open, onClose }: { steps: WalkthroughStep[]; open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  const [index, setIndex] = useState(0)
  const [rect, setRect] = useState<Rect | null>(null)

  useEffect(() => { if (open) setIndex(0) }, [open])
  useEffect(() => {
    if (!open || !steps.length) return
    const target = document.querySelector<HTMLElement>(steps[index]?.target)
    target?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
    let frame = 0
    const measure = () => {
      if (frame) cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const r = target?.getBoundingClientRect()
        const next = r && r.width && r.height ? { x: r.left, y: r.top, width: r.width, height: r.height } : null
        setRect((old) => next && old && Math.abs(next.x - old.x) < .5 && Math.abs(next.y - old.y) < .5 && Math.abs(next.width - old.width) < .5 && Math.abs(next.height - old.height) < .5 ? old : next)
      })
    }
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    const poll = window.setInterval(measure, 120)
    const observer = target ? new ResizeObserver(measure) : null
    if (target && observer) observer.observe(target)
    return () => { if (frame) cancelAnimationFrame(frame); window.clearInterval(poll); window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true); observer?.disconnect() }
  }, [open, index, steps.length, steps[index]?.target])
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); if (e.key === 'ArrowRight') setIndex((i) => Math.min(steps.length - 1, i + 1)); if (e.key === 'ArrowLeft') setIndex((i) => Math.max(0, i - 1)) }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [open, onClose, steps.length])

  if (!open || !steps.length) return null
  const step = steps[index]
  const pad = 6
  const x = rect ? Math.max(0, rect.x - pad) : 0
  const y = rect ? Math.max(0, rect.y - pad) : 0
  const right = rect ? Math.min(window.innerWidth, rect.x + rect.width + pad) : window.innerWidth
  const bottom = rect ? Math.min(window.innerHeight, rect.y + rect.height + pad) : window.innerHeight
  const panelWidth = Math.min(340, window.innerWidth - 32)
  const left = rect
    ? Math.max(16, Math.min(rect.x + rect.width / 2 > window.innerWidth / 2 ? rect.x - panelWidth - 16 : rect.x + rect.width + 16, window.innerWidth - panelWidth - 16))
    : Math.max(16, (window.innerWidth - panelWidth) / 2)
  const top = rect ? Math.max(16, Math.min(rect.y, window.innerHeight - 230)) : Math.max(16, (window.innerHeight - 230) / 2)

  return (
    <div className="walkthrough" onClick={(e) => e.stopPropagation()}>
      <div className="walkthrough-shade" style={{ left: 0, top: 0, width: '100%', height: y }} />
      <div className="walkthrough-shade" style={{ left: 0, top: y, width: x, height: bottom - y }} />
      <div className="walkthrough-shade" style={{ left: right, top: y, width: window.innerWidth - right, height: bottom - y }} />
      <div className="walkthrough-shade" style={{ left: 0, top: bottom, width: '100%', height: window.innerHeight - bottom }} />
      {rect && <div className="walkthrough-ring" style={{ left: x, top: y, width: right - x, height: bottom - y }} />}
      <section className="walkthrough-card" role="region" aria-live="polite" aria-label={step.title} style={{ left, top, width: panelWidth }}>
        <div className="walkthrough-top"><span>{t('guide.step', { n: index + 1, total: steps.length })}</span><button className="walkthrough-close" onClick={onClose} aria-label={t('guide.close')}><Icon name="x" size={16} /></button></div>
        <h2>{step.title}</h2><p>{step.body}</p>
        <div className="walkthrough-actions">
          <button className="btn linkish sm" onClick={onClose}>{t('guide.skip')}</button><span className="grow" />
          {index > 0 && <button className="btn sm" onClick={() => setIndex((i) => i - 1)}>{t('guide.previous')}</button>}
          <button className="btn sm primary" onClick={() => index === steps.length - 1 ? onClose() : setIndex((i) => i + 1)}>{index === steps.length - 1 ? t('guide.done') : t('guide.next')}</button>
        </div>
      </section>
    </div>
  )
}
