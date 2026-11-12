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

export function HeroArt({ variant = 'band' }: { variant?: 'band' | 'full' }) {
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
