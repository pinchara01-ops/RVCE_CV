import { Aperture } from 'lucide-react'
import { navigate, usePathname } from '../lib/router'
import { useLanguage } from '../lib/settings'
import { stringsFor } from '../lib/i18n'
import { LanguageSelect } from './LanguageSelect'

const LINKS = [
  { path: '/', key: 'navQuery' as const },
  { path: '/how-it-works', key: 'navHowItWorks' as const },
  { path: '/preprocess', key: 'navUpload' as const },
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
    <nav className="relative z-20 px-6 py-5">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-3 rounded-full px-4 py-2">
        <a href="/" onClick={go('/')} className="flex shrink-0 items-center gap-2">
          <Aperture size={22} className="text-glow" />
          <span className="text-lg font-semibold tracking-tight text-white">{t.productName}</span>
        </a>

        <div className="flex flex-1 items-center justify-end gap-5 sm:gap-7">
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
      </div>
    </nav>
  )
}
