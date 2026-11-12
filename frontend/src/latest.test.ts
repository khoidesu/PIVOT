import { describe, expect, it } from 'vitest'
import { latestGuard } from './latest'

describe('latestGuard', () => {
  it('chỉ lần gọi mới nhất là hiện hành', () => {
    const g = latestGuard()
    const a = g.next(), b = g.next()
    expect(g.current(a)).toBe(false)
    expect(g.current(b)).toBe(true)
  })

  it('phản hồi chậm của lần gọi cũ không ghi đè lần mới (mô phỏng useData)', async () => {
    const g = latestGuard()
    let data = ''
    const load = async (label: string, ms: number) => {
      const id = g.next()
      await new Promise((r) => setTimeout(r, ms))
      if (g.current(id)) data = label
    }
    await Promise.all([load('cũ (chậm)', 30), load('mới (nhanh)', 5)])
    expect(data).toBe('mới (nhanh)')
  })
})
