import { useEffect } from 'react'

const SURFACES = '.card, .fact, .note, .ws-win, .ws-start-card, .ws-node, .ws-rail, .ws-pop, .ws-bar, .nav, .hero, .land-step'

/** Decorative, delegated pointer glow for existing surfaces; does not intercept clicks or alter their behavior. */
export function MagicGlow() {
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let active: HTMLElement | null = null
    const move = (event: PointerEvent) => {
      const next = event.target instanceof Element ? event.target.closest<HTMLElement>(SURFACES) : null
      if (active !== next) {
        active?.removeAttribute('data-magic-active')
        active = next
        if (active) {
          active.classList.add('magic-glow-target')
          active.setAttribute('data-magic-active', '')
        }
      }
      if (!active) return
      const rect = active.getBoundingClientRect()
      active.style.setProperty('--magic-x', `${event.clientX - rect.left}px`)
      active.style.setProperty('--magic-y', `${event.clientY - rect.top}px`)
    }
    const leave = (event: PointerEvent) => {
      if (!event.relatedTarget) {
        active?.removeAttribute('data-magic-active')
        active = null
      }
    }
    window.addEventListener('pointermove', move, { passive: true })
    document.addEventListener('pointerout', leave)
    return () => {
      window.removeEventListener('pointermove', move)
      document.removeEventListener('pointerout', leave)
      active?.removeAttribute('data-magic-active')
    }
  }, [])

  return null
}
