// Menu theo vai trò: chỉ hiện các mục liên quan. Điều phối viên không có "Yêu cầu" (không tạo được) nhưng thấy phần còn lại;
// "Kịch bản demo" không nằm ở menu chính mà ở menu avatar của Điều phối viên.
import type { Role } from './api'

export type Route = 'request' | 'fleet' | 'recommend' | 'confirm' | 'timeline' | 'benefits' | 'demo' | 'tracking' | 'exceptions' | 'docks'

const NAV: Record<Role, Route[]> = {
  shipper: ['request', 'fleet', 'recommend', 'confirm', 'tracking', 'exceptions', 'timeline', 'benefits'],
  carrier: ['fleet', 'recommend', 'confirm', 'docks', 'tracking', 'exceptions', 'timeline', 'benefits'],
  node_operator: ['fleet', 'confirm', 'docks', 'tracking', 'exceptions', 'timeline'],
  dispatcher: ['fleet', 'recommend', 'confirm', 'docks', 'tracking', 'exceptions', 'timeline', 'benefits'],
}
// được vào bằng đường dẫn/nút dù không nằm ở menu (nhà vận tải có thể là forwarder tạo yêu cầu)
const EXTRA: Record<Role, Route[]> = { shipper: [], carrier: ['request'], node_operator: [], dispatcher: ['demo'] }

export const navFor = (role: string | undefined): Route[] => (role && NAV[role as Role]) || []
export const defaultRoute = (role: string | undefined): Route => (role === 'shipper' ? 'request' : 'fleet')
export const allowedRoute = (role: string | undefined, route: string): route is Route =>
  !!role && ([...(NAV[role as Role] ?? []), ...(EXTRA[role as Role] ?? [])] as string[]).includes(route)
