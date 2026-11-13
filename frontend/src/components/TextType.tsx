import { useEffect, useState } from 'react'

export function TextType({ text }: { text: string }) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    setShown(0)
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setShown(text.length); return }
    let index = 0
    const timer = window.setInterval(() => { index += 1; setShown(index); if (index >= text.length) window.clearInterval(timer) }, 28)
    return () => window.clearInterval(timer)
  }, [text])
  return <p className="land-sub text-type" aria-label={text}><span aria-hidden="true">{text.slice(0, shown)}</span><span className="text-type-cursor" aria-hidden="true" /></p>
}
