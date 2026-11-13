import { useMemo, useRef } from 'react'
import { gsap, reducedMotion, useGSAP } from '../motion'

// Hình minh hoạ đẳng cự VẼ BẰNG MÃ (không dùng ảnh ngoài): bãi container xếp cao dần + vệt đèn xe trên mặt bãi.
// Chỉ để trang trí (aria-hidden) — không biểu diễn dữ liệu thật nào. Màu lấy từ token nên theo chế độ sáng/tối.
const TW = 44, TH = 22, BH = 20 // nửa rộng/nửa cao của mặt trên, chiều cao một tầng

/** PRNG nhỏ có hạt giống: hình giống nhau giữa các lần render và giữa các cửa sổ. */
function rng(seed: number) {
  let s = seed
  return () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296 }
}

interface Box { key: string; x: number; y: number; cls: string; depth: number }

function layout(cols: number, rows: number, maxH: number, seed: number): { boxes: Box[]; w: number; h: number; ox: number; oy: number } {
  const r = rng(seed)
  const boxes: Box[] = []
  for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
    const ramp = (i + (rows - j) * 0.35) / (cols + rows * 0.35)        // cao dần về bên phải (như bãi container xếp tầng)
    const h = Math.max(0, Math.round(ramp * maxH + (r() - 0.55) * 2))
    if (h === 0 || (j === Math.floor(rows / 2) && i < cols - 2)) continue // chừa một làn đường cho vệt đèn xe
    for (let k = 0; k < h; k++) {
      const pick = r()
      const cls = pick > 0.93 ? 'ca' : pick > 0.86 ? 'co' : `c${Math.floor(r() * 3)}`
      boxes.push({ key: `${i}-${j}-${k}`, x: (i - j) * TW, y: (i + j) * TH - k * BH, cls, depth: i + j + k * 0.01 })
    }
  }
  boxes.sort((a, b) => a.depth - b.depth) // vẽ từ xa tới gần
  const xs = boxes.map((b) => b.x), ys = boxes.map((b) => b.y)
  const minX = Math.min(...xs) - TW, maxX = Math.max(...xs) + TW, minY = Math.min(...ys) - TH, maxY = Math.max(...ys) + TH + BH
  return { boxes, w: maxX - minX, h: maxY - minY, ox: -minX, oy: -minY }
}

const top = (x: number, y: number) => `${x},${y - TH} ${x + TW},${y} ${x},${y + TH} ${x - TW},${y}`
const left = (x: number, y: number) => `${x - TW},${y} ${x},${y + TH} ${x},${y + TH + BH} ${x - TW},${y + BH}`
const right = (x: number, y: number) => `${x + TW},${y} ${x},${y + TH} ${x},${y + TH + BH} ${x + TW},${y + BH}`

// ---------------------------------------------------------------- cảnh 3D theo vai trò (đẳng cự, vẽ bằng khối hộp)
type Cub = { i: number; j: number; k: number; di: number; dj: number; dk: number; cls: string }
const cb = (i: number, j: number, k: number, di: number, dj: number, dk: number, cls: string): Cub => ({ i, j, k, di, dj, dk, cls })
const P = (i: number, j: number, k: number): [number, number] => [(i - j) * TW, (i + j) * TH - k * BH]
const pts = (a: [number, number][]) => a.map(([x, y]) => `${x},${y}`).join(' ')
/** Ba mặt nhìn thấy của một khối hộp: mặt trên, mặt hướng +j (trái), mặt hướng +i (phải). */
function faces(c: Cub, ox: number, oy: number) {
  const q = (i: number, j: number, k: number): [number, number] => { const [x, y] = P(i, j, k); return [x + ox, y + oy] }
  const i1 = c.i + c.di, j1 = c.j + c.dj, k1 = c.k + c.dk
  return {
    top: pts([q(c.i, c.j, k1), q(i1, c.j, k1), q(i1, j1, k1), q(c.i, j1, k1)]),
    left: pts([q(c.i, j1, k1), q(i1, j1, k1), q(i1, j1, c.k), q(c.i, j1, c.k)]),
    right: pts([q(i1, c.j, k1), q(i1, j1, k1), q(i1, j1, c.k), q(i1, c.j, c.k)]),
  }
}
const win = (i: number, j: number, k: number, face: 'j' | 'i', w = 0.42, h = 0.5): Cub => (face === 'j' ? cb(i, j, k, w, 0.04, h, 'cw') : cb(i, j, k, 0.04, w, h, 'cw'))

/** Nhà vận tải: xe đầu kéo + rơ-moóc trên đường, vài kiện hàng bên lề. */
function truckScene(): Cub[] {
  const o: Cub[] = [cb(-1.2, -0.7, -0.12, 9.6, 3.6, 0.12, 'c2'), cb(1.0, -2.1, 0, 1.2, 1.0, 0.9, 'c1'), cb(2.4, -2.1, 0, 1.2, 1.0, 0.9, 'ca'), cb(1.0, -2.1, 0.9, 1.2, 1.0, 0.7, 'c0')]
  for (let i = -0.6; i < 7.4; i += 1.5) o.push(cb(i, 2.45, 0, 0.8, 0.12, 0.02, 'co')) // vạch kẻ đường
  o.push(cb(0, 0.1, 0.35, 5.6, 1.6, 0.15, 'c2'))                                       // sàn xe
  o.push(cb(0, 0.1, 0.5, 3.9, 1.6, 1.6, 'cl'), cb(0.35, 1.7, 0.85, 3.2, 0.04, 0.8, 'ca'))  // rơ-moóc + dải màu
  o.push(cb(4.1, 0.1, 0.5, 1.5, 1.6, 1.2, 'co'), cb(5.6, 0.45, 1.0, 0.04, 1.0, 0.55, 'cw'), cb(4.4, 1.7, 1.0, 0.8, 0.04, 0.5, 'cw'), cb(4.1, 0.1, 1.7, 1.2, 1.6, 0.14, 'c1')) // cabin, kính, ốp nóc
  for (const i of [0.5, 1.7, 4.4]) o.push(cb(i, 1.7, 0, 0.85, 0.28, 0.62, 'cd'), cb(i + 0.28, 1.98, 0.18, 0.3, 0.04, 0.26, 'c2')) // bánh + mâm
  return o
}

/** Điều hành ICD: toà văn phòng, chốt cổng có thanh chắn, vài container. */
function officeScene(): Cub[] {
  const o: Cub[] = [cb(-1.2, -1.2, -0.12, 9.4, 6.6, 0.12, 'c2'), cb(3.7, -1.0, 0, 1.2, 1.0, 0.8, 'c1'), cb(3.7, -1.0, 0.8, 1.2, 1.0, 0.8, 'co'), cb(5.1, -1.0, 0, 1.2, 1.0, 0.8, 'c0')]
  o.push(cb(0, 0, 0, 2.6, 2.4, 4, 'cl'), cb(0.4, 0.3, 4, 1.8, 1.8, 0.8, 'c1'), cb(0.8, 0.7, 4.8, 1.0, 1.0, 0.25, 'ca'))
  for (const k of [0.9, 1.7, 2.5, 3.3]) for (const i of [0.3, 1.0, 1.7]) o.push(win(i, 2.4, k, 'j'))
  for (const k of [0.9, 1.7, 2.5, 3.3]) for (const j of [0.3, 1.0, 1.7]) o.push(win(2.6, j, k, 'i'))
  o.push(cb(0.9, 2.4, 0, 0.7, 0.05, 0.75, 'ca'))                                     // cửa chính
  o.push(cb(4.3, 1.4, 0, 1.7, 1.4, 1.0, 'c0'), cb(4.1, 1.2, 1.0, 2.1, 1.8, 0.16, 'co'), cb(4.7, 2.8, 0.3, 0.7, 0.04, 0.45, 'cw')) // chốt cổng
  o.push(cb(6.5, 2.4, 0, 0.16, 0.16, 1.0, 'c2'), cb(6.5, 0.5, 0.95, 0.12, 1.95, 0.12, 'ca'))                               // thanh chắn
  return o
}

/** Điều phối viên: cảng biển — cầu cảng, tàu chở container, cẩu giàn đang nâng một container. */
function portScene(): Cub[] {
  const o: Cub[] = [cb(-1.2, -1.2, -0.12, 9.2, 6.2, 0.12, 'c2'), cb(-1.2, -1.2, 0, 9.2, 2.4, 0.3, 'c1')]
  for (const i of [-0.8, 0.4, 5.6]) o.push(cb(i, -0.8, 0.3, 1.0, 0.9, 0.7, i === 0.4 ? 'co' : 'c0'))
  for (const [i, j] of [[1.9, 0.0], [1.9, 0.95], [3.4, 0.0], [3.4, 0.95]] as const) o.push(cb(i, j, 0.3, 0.22, 0.22, 3.1, 'co')) // chân cẩu
  o.push(cb(0, 1.8, 0.0, 7.2, 2.2, 0.75, 'cl'), cb(0, 4.0, 0.42, 7.2, 0.04, 0.16, 'ca'), cb(7.2, 1.8, 0.42, 0.04, 2.2, 0.16, 'ca'))                                       // thân tàu + dải
  for (let n = 0; n < 5; n++) for (const j of [2.0, 3.0]) o.push(cb(0.4 + n * 1.15, j, 0.75, 1.05, 0.9, 0.7, (n + (j > 2.5 ? 1 : 0)) % 3 === 0 ? 'c1' : (n + (j > 2.5 ? 2 : 0)) % 4 === 0 ? 'co' : 'c2'))
  o.push(cb(1.6, 2.0, 1.45, 1.05, 0.9, 0.7, 'c1'), cb(2.75, 3.0, 1.45, 1.05, 0.9, 0.7, 'ca'))                                   // tầng hai
  o.push(cb(6.0, 2.1, 0.75, 1.0, 1.7, 1.7, 'c1'), cb(6.1, 3.8, 1.5, 0.7, 0.04, 0.45, 'cw'), cb(6.3, 2.5, 2.45, 0.45, 0.45, 0.6, 'ca')) // đài chỉ huy + ống khói
  o.push(cb(1.9, 0.0, 3.4, 0.22, 3.7, 0.22, 'co'), cb(3.4, 0.0, 3.4, 0.22, 3.7, 0.22, 'co'), cb(1.9, 0.0, 3.62, 1.72, 0.22, 0.22, 'co'), cb(1.9, 0.95, 3.4, 1.72, 0.22, 0.22, 'co')) // dầm cẩu
  return o
}
const SCENES = { carrier: truckScene, node_operator: officeScene, dispatcher: portScene } as const
export type SceneRole = keyof typeof SCENES

function ScenePic({ role }: { role: SceneRole }) {
  const ref = useRef<HTMLDivElement>(null)
  const { list, w, h, ox, oy } = useMemo(() => {
    const list = SCENES[role]()
    const xs: number[] = [], ys: number[] = []
    for (const c of list) for (const i of [c.i, c.i + c.di]) for (const j of [c.j, c.j + c.dj]) for (const k of [c.k, c.k + c.dk]) { const [x, y] = P(i, j, k); xs.push(x); ys.push(y) }
    const minX = Math.min(...xs) - 8, maxX = Math.max(...xs) + 8, minY = Math.min(...ys) - 8, maxY = Math.max(...ys) + 8
    return { list, w: maxX - minX, h: maxY - minY, ox: -minX, oy: -minY }
  }, [role])
  // phần treo (container đang nâng) của cảng: thêm sau cùng để luôn nằm trên mọi khối
  const hung = role === 'dispatcher' ? [cb(2.05, 2.55, 2.15, 1.05, 0.9, 0.7, 'ca'), cb(2.5, 2.9, 2.85, 0.04, 0.04, 0.55, 'cd'), cb(2.55, 2.9, 2.85, 0.04, 0.04, 0.55, 'cd')] : []
  useGSAP(() => {
    if (reducedMotion()) return
    gsap.from('.hb', { opacity: 0, y: 22, duration: 0.55, stagger: { each: 0.007, from: 'start' } })
    if (role === 'carrier') gsap.from('.scene-body', { x: -60, duration: 1, ease: 'power3.out' })
    if (role === 'dispatcher') gsap.to('.hb.hung', { y: -9, duration: 1.8, ease: 'sine.inOut', yoyo: true, repeat: -1 })                       // container đung đưa
    if (role === 'node_operator') gsap.to('.hb.cw', { opacity: 0.35, duration: 1.4, ease: 'sine.inOut', yoyo: true, repeat: -1, stagger: { each: 0.19, from: 'random' } }) // cửa sổ chớp
  }, { scope: ref, dependencies: [role] })
  const draw = (c: Cub, n: string, extra = '') => { const f = faces(c, ox, oy); return <g key={n} className={`hb ${c.cls}${extra}`}><polygon className="fl" points={f.left} /><polygon className="fr" points={f.right} /><polygon className="ft" points={f.top} /></g> }
  return (
    <div className="hero-art scene" aria-hidden ref={ref} data-scene={role}>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMaxYMid slice" focusable="false">
        <g className="scene-body">{list.map((c, n) => draw(c, String(n)))}</g>
        {hung.map((c, n) => draw(c, `h${n}`, ' hung'))}
      </svg>
    </div>
  )
}

export function HeroArt({ variant = 'band', scene }: { variant?: 'band' | 'full'; scene?: string }) {
  if (scene && scene in SCENES) return <ScenePic role={scene as SceneRole} />
  const full = variant === 'full'

  const ref = useRef<HTMLDivElement>(null)
  const { boxes, w, h, ox, oy, lane } = useMemo(() => {
    const cols = full ? 11 : 8, rows = full ? 7 : 5
    const l = layout(cols, rows, full ? 6 : 4, full ? 7 : 3)
    const j = Math.floor(rows / 2)                                       // làn đường: chạy dọc theo trục i ở hàng giữa
    const p = (i: number, dj = 0) => `${(i - (j + dj)) * TW + l.ox},${(i + j + dj) * TH + l.oy + TH}`
    return { ...l, lane: [`M${p(-1)} L${p(cols - 2)}`, `M${p(-1, 0.45)} L${p(cols - 3, 0.45)}`] }
  }, [full])

  useGSAP(() => {
    if (reducedMotion()) return
    gsap.from('.hb', { opacity: 0, y: 26, duration: 0.6, stagger: { each: full ? 0.006 : 0.008, from: 'start' } })
    gsap.utils.toArray<SVGPathElement>('.trail').forEach((path, n) => {
      const len = path.getTotalLength()
      gsap.set(path, { strokeDasharray: `${len * 0.22} ${len}`, strokeDashoffset: len * 0.22 })
      const tween = gsap.to(path, { strokeDashoffset: -len, duration: 3.2 + n * 0.9, ease: 'none', delay: 0.5 + n * 0.6, repeat: full ? -1 : 0, repeatDelay: 1.2 })
      if (!full) tween.eventCallback('onComplete', () => gsap.set(path, { opacity: 0 })) // trong cửa sổ: chỉ chạy một lượt (không tốn khung hình nền)
    })
  }, { scope: ref })

  return (
    <div className="hero-art" aria-hidden ref={ref}>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio={full ? 'xMaxYMid meet' : 'xMaxYMid slice'} focusable="false">
        <path className="trail o" d={lane[0]} />
        <path className="trail a" d={lane[1]} />
        {boxes.map((b) => {
          const x = b.x + ox, y = b.y + oy
          return <g key={b.key} className={`hb ${b.cls}`}><polygon className="fl" points={left(x, y)} /><polygon className="fr" points={right(x, y)} /><polygon className="ft" points={top(x, y)} /></g>
        })}
      </svg>
    </div>
  )
}
