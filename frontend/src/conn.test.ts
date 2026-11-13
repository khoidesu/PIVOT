import { describe, expect, it } from 'vitest'
import { ApiError } from './api'
import { multiTenant } from './fmt'
import { isConnError } from './conn'

describe('QA-07: phân biệt lỗi kết nối với lỗi nghiệp vụ', () => {
  it('mất mạng / máy chủ lỗi 5xx là lỗi kết nối', () => {
    expect(isConnError(new ApiError(0, 'NETWORK', 'x'))).toBe(true)
    expect(isConnError(new ApiError(502, 'UNKNOWN', 'x'))).toBe(true)
  })
  it('4xx (quyền, dữ liệu sai) không phải lỗi kết nối', () => {
    expect(isConnError(new ApiError(403, 'FORBIDDEN', 'x'))).toBe(false)
    expect(isConnError(new ApiError(422, 'VALIDATION', 'x'))).toBe(false)
    expect(isConnError(new ApiError(0, 'UNKNOWN', 'TypeError'))).toBe(false)
    expect(isConnError(null)).toBe(false)
  })
})

describe('QA-10: ghi tên tổ chức khi thấy lô của nhiều tổ chức', () => {
  it('một tổ chức → không cần', () => expect(multiTenant([{ tenant_id: 'a' }, { tenant_id: 'a' }])).toBe(false))
  it('nhiều tổ chức → cần', () => expect(multiTenant([{ tenant_id: 'a' }, { tenant_id: 'b' }])).toBe(true))
})
