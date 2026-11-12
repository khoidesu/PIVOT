import { useEffect } from 'react'
import { api } from '../api'
import { useI18n } from '../i18n'
import { applyTheme, isTheme } from '../theme'
import { useData } from '../useData'

/** Chỉ chạy trong cửa sổ nhúng: báo cho trang bao ngoài số việc đang chờ người này (hiện ở thanh bên). */
export function EmbedBridge() {
  const { setLang } = useI18n()
  const proposals = useData(() => api.proposals(), 5000)
  const notes = useData(() => api.notifications(), 5000)
  const n = (proposals.data ?? []).filter((p) => p.my_actions.accept).length + (notes.data?.unread ?? 0)
  useEffect(() => { window.parent.postMessage({ type: 'logection:badge', n }, location.origin) }, [n])
  useEffect(() => { // ngôn ngữ do trang bao ngoài quyết định (đổi một nơi, mọi cửa sổ đổi theo)
    const on = (e: MessageEvent) => {
      const d = e.data as { type?: string; lang?: string; theme?: string } | null
      if (e.origin !== location.origin || e.source !== window.parent) return
      if (d?.type === 'logection:lang' && (d.lang === 'vi' || d.lang === 'en')) setLang(d.lang)
      else if (d?.type === 'logection:theme' && isTheme(d.theme)) applyTheme(d.theme) // trang bao ngoài quyết định chế độ sáng/tối
    }
    window.addEventListener('message', on)
    return () => window.removeEventListener('message', on)
  }, [setLang])
  return null
}
