import { Aperture } from 'lucide-react'
import { navigate, usePathname } from '../lib/router'
import { useLanguage } from '../lib/settings'
import { stringsFor } from '../lib/i18n'
import { LanguageSelect } from './LanguageSelect'

const LINKS = [
  { path: '/', key: 'navQuery' as const },
  { path: '/how-it-works', key: 'navHowItWorks' as const },
  { path: '/preprocess', key: 'navUpload' as const },
  { path: '/design', key: 'navDesign' as const },
  { path: '/tests', key: 'navTests' as const },
  { path: '/developer', key: 'navDeveloper' as const },
]

export function Nav() {
  const pathname = usePathname()
  const [language, setLanguage] = useLanguage()
  const t = stringsFor(language)

  const go = (path: string) => (event: React.MouseEvent) => {
    event.preventDefault()
    navigate(path)
  }

  return (
    <nav className="relative z-20 px-4 py-4 sm:px-6 sm:py-5">
      <div className="mx-auto max-w-6xl rounded-2xl px-1 py-2 sm:px-4">
        <div className="flex items-center justify-between gap-4">
        <a href="/" onClick={go('/')} className="flex shrink-0 items-center gap-2">
          <Aperture size={22} className="text-glow" />
          <span className="text-lg font-semibold tracking-tight text-white">{t.productName}</span>
        </a>

        <div className="hidden flex-1 items-center justify-end gap-5 md:flex lg:gap-7">
          {LINKS.map((link) => (
            <a
              key={link.path}
              href={link.path}
              onClick={go(link.path)}
              className={`whitespace-nowrap text-sm font-medium transition-colors hover:text-white ${
                pathname === link.path ? 'text-white' : 'text-white/70'
              }`}
            >
              {t[link.key]}
            </a>
          ))}

          {/* Language sits in the chrome rather than beside the query: it
              governs the whole interface and every response, not one search. */}
          <LanguageSelect value={language} onChange={setLanguage} disabled={false} />
        </div>
        <div className="md:hidden">
          <LanguageSelect value={language} onChange={setLanguage} disabled={false} />
        </div>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-1 border-t border-white/10 pt-3 md:hidden">
          {LINKS.filter((link) => ['/', '/how-it-works', '/tests'].includes(link.path)).map((link) => (
            <a
              key={link.path}
              href={link.path}
              onClick={go(link.path)}
              className={`rounded-full px-2 py-2 text-center text-xs font-medium transition-colors hover:bg-white/5 hover:text-white ${
                pathname === link.path ? 'bg-white/5 text-white' : 'text-white/60'
              }`}
            >
              {t[link.key]}
            </a>
          ))}
        </div>
      </div>
    </nav>
  )
}
