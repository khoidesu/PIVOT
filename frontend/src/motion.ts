// Chuyển động dàn dựng bằng GSAP. Quy ước (skill gsap-react): mọi tween tạo trong useGSAP có scope → tự dọn khi unmount;
// hàm chạy SAU đó (MutationObserver, ResizeObserver) bọc contextSafe. Chỉ đụng transform/opacity (không gây layout).
// Người dùng bật "giảm chuyển động" → không tạo tween nào, giao diện hiện ngay trạng thái cuối.
import { useRef, type RefObject } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'

gsap.registerPlugin(useGSAP)
gsap.defaults({ ease: 'power3.out', duration: 0.45 })

export const reducedMotion = () => {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return true }
}

const BLOCKS = '.card, .note, .empty, .ws-win'
const POPS = '.menu, .ws-pop'

/** Phần tử MỚI xuất hiện trong `ref` (thẻ, ghi chú, cửa sổ, menu) trượt nhẹ vào — kể cả khi dữ liệu về sau lần render đầu.
 *  Polling không tạo lại nút DOM (React giữ theo key) nên không bị nháy lại; chỉ phần tử ngoài cùng của mỗi đợt được chạy. */
export function useAutoEnter(ref: RefObject<HTMLElement | null>, deps: unknown[] = []) {
  useGSAP((_ctx, contextSafe) => {
    const root = ref.current
    if (!root || reducedMotion() || !contextSafe) return
    const seen = new WeakSet<Element>()
    let queue: Element[] = []
    let raf = 0
    const flush = contextSafe(() => {
      raf = 0
      const batch = queue.filter((el) => el.isConnected)
      queue = []
      const outer = batch.filter((el) => !batch.some((o) => o !== el && o.contains(el)))
      const pops = outer.filter((el) => el.matches(POPS))
      const blocks = outer.filter((el) => !el.matches(POPS))
      if (blocks.length) gsap.fromTo(blocks, { opacity: 0, y: 14 }, { opacity: 1, y: 0, stagger: 0.05, clearProps: 'opacity,transform', overwrite: 'auto' })
      if (pops.length) gsap.fromTo(pops, { opacity: 0, scale: 0.96, y: -4 }, { opacity: 1, scale: 1, y: 0, duration: 0.2, ease: 'power2.out', clearProps: 'opacity,transform' })
    })
    const add = (el: Element) => {
      if (seen.has(el)) return
      seen.add(el); queue.push(el)
      if (!raf) raf = requestAnimationFrame(flush)
    }
    const scan = (n: Node) => {
      if (!(n instanceof Element)) return
      if (n.matches(`${BLOCKS}, ${POPS}`)) add(n)
      n.querySelectorAll(`${BLOCKS}, ${POPS}`).forEach(add)
    }
    scan(root)
    const mo = new MutationObserver((ms) => { for (const m of ms) m.addedNodes.forEach(scan) })
    mo.observe(root, { childList: true, subtree: true })
    return () => { mo.disconnect(); cancelAnimationFrame(raf) }
  }, { scope: ref, dependencies: deps })
}

/** Viên chỉ mục của thanh điều hướng trượt tới mục đang chọn (đổi màn, đổi ngôn ngữ, đổi kích thước cửa sổ). */
export function useNavIndicator(navRef: RefObject<HTMLElement | null>, indRef: RefObject<HTMLElement | null>, deps: unknown[]) {
  const first = useRef(true)
  useGSAP((_ctx, contextSafe) => {
    const nav = navRef.current, ind = indRef.current
    if (!nav || !ind || !contextSafe) return
    const place = contextSafe((animate: boolean) => {
      const cur = nav.querySelector<HTMLElement>('a[aria-current="page"]')
      if (!cur) { gsap.set(ind, { opacity: 0 }); return }
      const to = { x: cur.offsetLeft, width: cur.offsetWidth, opacity: 1 }
      if (animate && !reducedMotion()) gsap.to(ind, { ...to, duration: 0.4, overwrite: true })
      else gsap.set(ind, to)
      cur.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    })
    place(!first.current)
    first.current = false
    const ro = new ResizeObserver(() => place(false))
    ro.observe(nav)
    return () => ro.disconnect()
  }, { dependencies: deps, scope: navRef })
}

export { gsap, useGSAP }
