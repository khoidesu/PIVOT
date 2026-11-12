import { describe, expect, it } from 'vitest'
import { fitSize, MAX_SIDE } from './image'

describe('fitSize', () => {
  it('thu nhỏ cạnh dài về giới hạn, giữ tỉ lệ', () => {
    expect(fitSize(4000, 3000)).toEqual({ w: MAX_SIDE, h: 1200 })
    expect(fitSize(3000, 4000)).toEqual({ w: 1200, h: MAX_SIDE })
  })
  it('ảnh nhỏ giữ nguyên, không phóng to', () => {
    expect(fitSize(800, 600)).toEqual({ w: 800, h: 600 })
  })
  it('không bao giờ ra kích thước 0', () => {
    expect(fitSize(100000, 1)).toEqual({ w: MAX_SIDE, h: 1 })
  })
})
