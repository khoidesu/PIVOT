const TZ = 'Asia/Ho_Chi_Minh' // múi giờ vận hành; backend lưu UTC (DRAFT mục 4.1)
const timeFmt = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
const timeFmtLong = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

let skewMs = 0 // chênh lệch đồng hồ server - client, để "tuổi dữ liệu" tính theo giờ server
export const setServerTime = (iso: string) => { skewMs = new Date(iso).getTime() - Date.now() }
export const nowMs = () => Date.now() + skewMs

export const fmtTime = (iso: string | null | undefined) => {
  if (!iso) return '—'
  const p = Object.fromEntries(timeFmt.formatToParts(new Date(iso)).map((x) => [x.type, x.value]))
  return `${p.day}/${p.month} ${p.hour}:${p.minute}` // dd/MM HH:mm theo giờ vận hành
}
export const fmtClock = (iso: string | null | undefined) => (iso ? timeFmtLong.format(new Date(iso)) : '—')
export const fmtVnd = (n: number | null | undefined) => (n == null ? '—' : `${Math.round(n).toLocaleString('vi-VN')} ₫`)
export const fmtNum = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('vi-VN'))
export const ageMinutes = (iso: string | null | undefined) => (iso ? Math.max(0, Math.round((nowMs() - new Date(iso).getTime()) / 60000)) : null)

/** Giá trị của <input type="datetime-local"> hiểu theo giờ Việt Nam (UTC+7) → ISO có múi giờ. */
export const localInputToIso = (v: string) => (v ? `${v}:00+07:00` : '')
/** Mặc định cho ô nhập: bây giờ + offset giờ, theo giờ Việt Nam. */
export function localInputDefault(offsetHours: number) {
  const d = new Date(nowMs() + offsetHours * 3600_000 + 7 * 3600_000)
  return d.toISOString().slice(0, 16)
}
