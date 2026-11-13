import { useRef } from 'react'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import background from '../../assets/background.png'
import { Chip } from '../components/ui'
import { Icon, type IconName } from '../components/Icon'
import DotGrid from '../components/DotGrid'
import { Brand } from '../components/TopBar'
import { TextType } from '../components/TextType'
import { useI18n } from '../i18n'
import { gsap, reducedMotion, useGSAP } from '../motion'

gsap.registerPlugin(ScrollTrigger)

const STEPS: { icon: IconName; key: 'g1' | 'g2' | 'g3' | 'g4' | 'g5' | 'g6' }[] = [
  { icon: 'plus', key: 'g1' }, { icon: 'box', key: 'g2' }, { icon: 'target', key: 'g3' },
  { icon: 'check', key: 'g4' }, { icon: 'truck', key: 'g5' }, { icon: 'coins', key: 'g6' },
]

/** Trang mở đầu: giới thiệu ngắn + nút Bắt đầu (vào khu làm việc) + hướng dẫn test prototype. Ảnh container là ảnh của nhóm, đã tách nền trời. */
export function Landing({ onStart }: { onStart: () => void }) {
  const { t, lang, setLang } = useI18n()
  const root = useRef<HTMLDivElement>(null)
  const guide = useRef<HTMLElement>(null)

  useGSAP(() => {
    if (reducedMotion()) return
    gsap.timeline({ defaults: { duration: 0.8 } })
      .from('.land-nav', { opacity: 0, y: -12, duration: 0.5 }, 0)
      .from('.land-copy > *:not(.land-title)', { opacity: 0, y: 30, stagger: 0.09 }, 0.1)
      .from('.land-title-word', { opacity: 0, y: -22, filter: 'blur(10px)', stagger: 0.12, duration: 0.75, ease: 'power3.out' }, 0.28)
      .from('.land-img', { opacity: 0, x: 60, duration: 1.1 }, 0.15)
    gsap.to('.land-img', { yPercent: -6, ease: 'none', scrollTrigger: { trigger: '.land-hero', start: 'top top', end: 'bottom top', scrub: true } }) // ảnh trôi chậm hơn chữ khi cuộn
    gsap.from('.land-step', { opacity: 0, y: 36, duration: 0.6, stagger: 0.1, scrollTrigger: { trigger: '.land-steps', start: 'top 82%' } })
  }, { scope: root })

  const toGuide = () => guide.current?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })

  return (
    <div className="land" ref={root}>
      <section className="land-hero">
        <img className="land-img" src={background} alt="" width={1774} height={887} decoding="async" />
        <DotGrid
          className="land-dots"
          baseColor="#756b82"
          activeColor="#dfff40"
          dotSize={2.4}
          gap={15}
          proximity={145}
          strength={0.65}
          bounce={0.5}
          tension={0.16}
          returnDuration={0.7}
          swell={0.55}
          stretch={0.18}
          glow={0.3}
          opacity={0.44}
          intro={false}
          mouseInteraction
          clickShock={false}
          dpr={undefined}
          style={undefined}
        />
        <header className="land-nav">
          <Brand />
          <button className="btn sm linkish" onClick={toGuide}>{t('land.guide')}</button>
          <span className="grow" />
          <div className="seg" role="group" aria-label="Language">
            {(['vi', 'en'] as const).map((l) => <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
          </div>
          <button className="btn sm primary" onClick={onStart}>{t('land.start')}</button>
        </header>
        <div className="land-copy">
          <Chip kind="sim">{t('badge.mock')}</Chip>
          <h1 className="land-title" aria-label={t('ws.hero.title')}>
            <span className="sr">{t('ws.hero.title')}</span>
            {t('ws.hero.title').split(' ').map((word, index) => <span className="land-title-word" aria-hidden="true" key={`${word}-${index}`}>{word}{'\u00a0'}</span>)}
          </h1>
          <TextType text={t('land.sub')} />
          <div className="row">
            <button className="btn primary" onClick={onStart}>{t('land.start')}</button>
            <button className="btn" onClick={toGuide}>{t('land.guide')}</button>
          </div>
        </div>
      </section>

      <section className="land-guide" ref={guide} aria-labelledby="land-guide-h">
        <h2 id="land-guide-h" className="land-h2">{t('land.guide')}</h2>
        <p className="land-guide-intro">{t('land.guideIntro')}</p>
        <ol className="land-steps">
          {STEPS.map((s, i) => (
            <li key={s.key} className="land-step">
              <span className="land-num">{String(i + 1).padStart(2, '0')}</span>
              <span className="land-ico"><Icon name={s.icon} size={18} /></span>
              <h3>{t(`land.${s.key}.t`)}</h3>
              <p>{t(`land.${s.key}.d`)}</p>
            </li>))}
        </ol>
      </section>
    </div>
  )
}
