import { useRef, type ReactNode } from 'react'
import { Icon, type IconName } from './Icon'
import { gsap, reducedMotion, useGSAP } from '../motion'

/** Ô hành động lớn cho hai lối nhập nhanh (dán tin nhắn / tải ảnh): biểu tượng, tên, một dòng mô tả.
 *  Chuyển động GSAP: vào lần lượt; rê chuột → ô nghiêng nhẹ theo con trỏ, biểu tượng nảy, vệt sáng quét qua. Tắt khi "giảm chuyển động". */
export function IntakeTile({ icon, title, sub, active, busy, disabled, onClick, index = 0, children }: {
  icon: IconName; title: string; sub: string; active?: boolean; busy?: boolean; disabled?: boolean; onClick: () => void; index?: number; children?: ReactNode
}) {
  const ref = useRef<HTMLButtonElement>(null)
  const { contextSafe } = useGSAP(() => {
    if (reducedMotion()) return
    gsap.from(ref.current, { opacity: 0, y: 16, scale: 0.97, duration: 0.5, delay: 0.08 * index, clearProps: 'opacity,transform' })
  }, { scope: ref })

  const enter = contextSafe(() => {
    if (reducedMotion() || disabled) return
    gsap.to('.tile-ico', { y: -3, rotate: -6, scale: 1.08, duration: 0.35, ease: 'back.out(2.2)' })
    gsap.fromTo('.tile-shine', { xPercent: -130, opacity: 0.9 }, { xPercent: 260, opacity: 0, duration: 0.75, ease: 'power2.out' })
    gsap.to('.tile-go', { x: 4, opacity: 1, duration: 0.25 })
  })
  const move = contextSafe((e: React.PointerEvent<HTMLButtonElement>) => {
    if (reducedMotion() || disabled || e.pointerType !== 'mouse') return
    const r = e.currentTarget.getBoundingClientRect()
    const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5
    gsap.to(ref.current, { rotateY: px * 5, rotateX: -py * 5, transformPerspective: 700, duration: 0.3, overwrite: 'auto' })
  })
  const leave = contextSafe(() => {
    if (reducedMotion()) return
    gsap.to('.tile-ico', { y: 0, rotate: 0, scale: 1, duration: 0.3 })
    gsap.to('.tile-go', { x: 0, opacity: 0.55, duration: 0.25 })
    gsap.to(ref.current, { rotateX: 0, rotateY: 0, duration: 0.45, ease: 'power3.out', overwrite: 'auto' })
  })

  return (
    <button ref={ref} type="button" className={`tile${active ? ' on' : ''}${busy ? ' busy' : ''}`} aria-expanded={active} aria-busy={busy || undefined} disabled={disabled}
      onClick={onClick} onPointerEnter={enter} onPointerMove={move} onPointerLeave={leave}>
      <span className="tile-shine" aria-hidden />
      <span className="tile-ico"><Icon name={icon} size={20} /></span>
      <span className="tile-txt"><b>{title}</b><small>{sub}</small></span>
      <span className="tile-go" aria-hidden><Icon name="arrowRight" size={16} /></span>
      {children}
    </button>
  )
}
