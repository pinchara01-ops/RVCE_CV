import { Globe } from 'lucide-react'

export function Nav() {
  const scrollToPipeline = (e: React.MouseEvent) => {
    e.preventDefault()
    document.getElementById('pipeline-section')?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <nav className="relative z-20 pl-6 pr-6 py-6">
      <div className="mx-auto flex max-w-5xl items-center justify-between rounded-full px-6 py-3">
        <div className="flex items-center gap-2">
          <Globe size={24} className="text-white" />
          <span className="text-lg font-semibold text-white">FootageAsk</span>
        </div>
        <div className="flex items-center gap-8">
          <a
            href="#pipeline-section"
            onClick={scrollToPipeline}
            className="hidden text-sm font-medium text-white/80 transition-colors hover:text-white md:inline"
          >
            How it works
          </a>
          <a
            href="#pipeline-section"
            className="hidden text-sm font-medium text-white/80 transition-colors hover:text-white md:inline"
          >
            Docs
          </a>
        </div>
      </div>
    </nav>
  )
}
