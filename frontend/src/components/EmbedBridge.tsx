import { useEffect } from 'react'
import { api } from '../api'
import { useI18n } from '../i18n'
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
      const d = e.data as { type?: string; lang?: string } | null
      if (e.origin === location.origin && e.source === window.parent && d?.type === 'logection:lang' && (d.lang === 'vi' || d.lang === 'en')) setLang(d.lang)
    }
    window.addEventListener('message', on)
    return () => window.removeEventListener('message', on)
  }, [setLang])
  return null
}
