import { Globe } from 'lucide-react'
import { navigate, usePathname } from '../lib/router'

export function Nav() {
  const pathname = usePathname()

  const goHome = (e: React.MouseEvent) => {
    e.preventDefault()
    navigate('/')
  }

  const scrollToPipeline = (e: React.MouseEvent) => {
    e.preventDefault()
    if (pathname !== '/') {
      navigate('/')
      return
    }
    document.getElementById('pipeline-section')?.scrollIntoView({ behavior: 'smooth' })
  }

  const goUpload = (e: React.MouseEvent) => {
    e.preventDefault()
    navigate('/upload')
  }

  return (
    <nav className="relative z-20 pl-6 pr-6 py-6">
      <div className="mx-auto flex max-w-5xl items-center justify-between rounded-full px-6 py-3">
        <a href="/" onClick={goHome} className="flex items-center gap-2">
          <Globe size={24} className="text-white" />
          <span className="text-lg font-semibold text-white">FootageAsk</span>
        </a>
        <div className="flex items-center gap-8">
          <a
            href="#pipeline-section"
            onClick={scrollToPipeline}
            className="text-sm font-medium text-white/80 transition-colors hover:text-white"
          >
            How it works
          </a>
          <a
            href="/upload"
            onClick={goUpload}
            className={`text-sm font-medium transition-colors hover:text-white ${
              pathname === '/upload' ? 'text-white' : 'text-white/80'
            }`}
          >
            Upload
          </a>
        </div>
      </div>
    </nav>
  )
}
