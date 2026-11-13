import { useEffect, useState } from 'react'
import { useI18n } from '../i18n'
import { ACCENT_PRESETS, type Theme } from '../theme'
import { Icon } from './Icon'

/** Bảng "Giao diện" dùng chung (khu làm việc + trang mở đầu): chế độ sáng/tối, màu nhấn có sẵn, mã màu tuỳ chọn. */
export function AppearancePanel({ theme, accent, onTheme, onAccent, className = '' }: {
  theme: Theme; accent: string; onTheme: (t: Theme) => void; onAccent: (c: string) => void; className?: string
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(accent)
  useEffect(() => { setDraft(accent) }, [accent])
  return (
    <section className={`ws-appearance-pop ${className}`} role="dialog" aria-label={t('theme.appearance')}>
      <h2>{t('theme.appearance')}</h2>
      <div className="ws-appearance-block">
        <span className="ws-appearance-label">{t('theme.mode')}</span>
        <div className="ws-mode-options" role="group" aria-label={t('theme.mode')}>
          {(['light', 'dark'] as const).map((m) => (
            <button key={m} className={theme === m ? 'on' : ''} aria-pressed={theme === m} onClick={() => onTheme(m)}>
              <Icon name={m === 'light' ? 'sun' : 'moon'} size={16} /><span>{t(`theme.${m}`)}</span>
            </button>))}
        </div>
      </div>
      <div className="ws-appearance-block">
        <span className="ws-appearance-label">{t('theme.accent')}</span>
        <div className="ws-color-grid" role="group" aria-label={t('theme.presets')}>
          {ACCENT_PRESETS.map((color) => (
            <button key={color} className={`ws-color-swatch${accent.toLowerCase() === color.toLowerCase() ? ' selected' : ''}`}
              style={{ backgroundColor: color }} aria-label={`${t('theme.accent')} ${color}`} title={color} aria-pressed={accent.toLowerCase() === color.toLowerCase()}
              onClick={() => onAccent(color)} />))}
        </div>
      </div>
      <div className="ws-custom-color">
        <span className="ws-appearance-label">{t('theme.custom')}</span>
        <label className="ws-color-hex">
          <span>{t('theme.hex')}</span>
          <input aria-label={t('theme.hex')} value={draft.toUpperCase()} maxLength={7}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => /^#[\da-f]{6}$/i.test(draft) ? onAccent(draft) : setDraft(accent)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.currentTarget.blur() } }} />
        </label>
        <label className="ws-color-picker" title={t('theme.colorPicker')}>
          <input type="color" aria-label={t('theme.colorPicker')} value={accent} onChange={(e) => onAccent(e.target.value)} />
          <span>{t('theme.colorPicker')}</span>
        </label>
      </div>
    </section>
  )
}
