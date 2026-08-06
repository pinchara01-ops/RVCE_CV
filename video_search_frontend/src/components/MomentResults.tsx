import { Film } from 'lucide-react'
import { clipUrl, type QuickMoment, type QuickSearchResponse } from '../lib/api'
import { formatTimestamp } from '../lib/format'
import type { Strings } from '../lib/i18n'

function MomentCard({
  moment,
  index,
  strings: t,
}: {
  moment: QuickMoment
  index: number
  strings: Strings
}) {
  const confidence = Math.round(moment.confidence * 100)

  return (
    <article className="liquid-glass overflow-hidden rounded-2xl border border-white/10 bg-ink-900/70">
      {moment.clip_url ? (
        <video
          controls
          preload="metadata"
          src={clipUrl(moment.clip_url)}
          className="aspect-video w-full bg-black"
        />
      ) : (
        <div className="flex aspect-video w-full items-center justify-center bg-ink-800 text-paper-300/25">
          <Film size={26} />
        </div>
      )}

      <div className="p-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-[11px] text-paper-300/40">#{index + 1}</span>
          <span className="font-mono text-[11px] text-paper-300/50">
            {formatTimestamp(moment.start)}, {formatTimestamp(moment.end)}
          </span>
        </div>

        <p className="mt-2 text-sm leading-relaxed text-paper-100">
          {moment.description || 'Matching moment'}
        </p>

        {!moment.clip_url && (
          <p className="mt-1.5 text-xs text-paper-300/40">
            This clip could not be prepared, but the moment is at the time shown above.
          </p>
        )}

        <div className="mt-3 flex items-center gap-2">
          <div className="h-1 w-20 overflow-hidden rounded-full bg-ink-700">
            <div className="h-full rounded-full bg-glow" style={{ width: `${confidence}%` }} />
          </div>
          <span className="font-mono text-[10px] text-paper-300/40">
            {confidence}% {t.matchSuffix}
          </span>
        </div>
      </div>
    </article>
  )
}

interface MomentResultsProps {
  strings: Strings
  response: QuickSearchResponse | null
  error: string | null
}

export function MomentResults({ strings: t, response, error }: MomentResultsProps) {
  if (error) {
    return (
      <div className="px-6 py-10 text-center">
        <p className="text-sm text-red-300/90">{error}</p>
      </div>
    )
  }

  if (!response) {
    return (
      <div className="px-6 py-10 text-center">
        <p className="text-sm text-paper-300/40">
          {t.momentsEmptyPrompt}
        </p>
      </div>
    )
  }

  return (
    <div className="px-5 py-5">
      <div className="mb-4">
        <p className="text-[11px] uppercase tracking-widest text-paper-300/40">
          {t.resultsFor} “{response.query}”
        </p>
        {response.summary && (
          <p className="mt-1.5 text-sm leading-relaxed text-paper-300/70">{response.summary}</p>
        )}
      </div>

      {response.moments.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-ink-800/40 px-4 py-8 text-center">
          <p className="text-sm text-paper-100">{t.noMatches}</p>
          <p className="mt-1 text-xs text-paper-300/50">
            {t.noMatchesBody}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {response.moments.map((moment, index) => (
            <MomentCard
              key={`${moment.start}-${index}`}
              moment={moment}
              index={index}
              strings={t}
            />
          ))}
        </div>
      )}
    </div>
  )
}
