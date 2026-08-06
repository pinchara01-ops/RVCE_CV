import { useEffect, useState, type ReactNode } from 'react'
import { Nav } from './Nav'
import { BackgroundVideo } from './BackgroundVideo'
import { useLanguage } from '../lib/settings'
import { RTL_LANGUAGES } from '../lib/i18n'

interface PageShellProps {
  children: ReactNode
  /** Extra height for the video band at the top of the page. */
  heroHeight?: string
}

/**
 * Shared page frame: the background video sits at the top of every page and
 * fades out as the reader scrolls past it, so content below is read against
 * plain black rather than moving footage.
 */
export function PageShell({ children, heroHeight = '60vh' }: PageShellProps) {
  const [language] = useLanguage()
  const rtl = RTL_LANGUAGES.has(language)
  const [opacity, setOpacity] = useState(1)

  useEffect(() => {
    const onScroll = () => {
      const fadeOver = window.innerHeight * 0.5
      setOpacity(Math.max(0, 1 - window.scrollY / fadeOver))
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div className="relative min-h-screen bg-black text-paper-100" dir={rtl ? 'rtl' : 'ltr'}>
      <div
        className="pointer-events-none fixed inset-x-0 top-0 -z-10 overflow-hidden"
        style={{ height: heroHeight, opacity }}
      >
        <BackgroundVideo />
        <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-black/30 to-black" />
      </div>

      <div className="relative z-10 flex min-h-screen flex-col">
        <Nav />
        {children}
      </div>
    </div>
  )
}
