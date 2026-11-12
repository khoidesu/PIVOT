import { describe, expect, it } from 'vitest'
import { acceptFor, fitSize, isPdf, MAX_SIDE } from './image'

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

describe('tệp PDF', () => {
  it('nhận PDF theo loại hoặc đuôi tệp (máy chủ vẫn kiểm tra nội dung)', () => {
    expect(isPdf({ type: 'application/pdf', name: 'x' })).toBe(true)
    expect(isPdf({ type: '', name: 'Phieu.PDF' })).toBe(true)
    expect(isPdf({ type: 'image/jpeg', name: 'a.jpg' })).toBe(false)
  })
  it('ô chọn tệp chỉ mời loại tệp máy chủ đọc được', () => {
    expect(acceptFor(false, true)).toBe('application/pdf,.pdf')
    expect(acceptFor(true, true)).toContain('image/png')
    expect(acceptFor(true, false)).not.toContain('pdf')
  })
})
