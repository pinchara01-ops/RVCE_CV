import { PageShell } from '../components/PageShell'
import { useLanguage } from '../lib/settings'
import { stringsFor } from '../lib/i18n'

const STAGES = [
  {
    title: 'Ingestion',
    body: 'The uploaded file is validated and probed with ffprobe for duration, streams, and container type. Duration matters: it is stated back to the model so returned timestamps cannot run past the end of the file.',
    detail: 'MP4, WebM, MOV, AVI, MKV. Audio-only inputs are accepted; the visual channel is simply empty.',
  },
  {
    title: 'Segmentation',
    body: 'Footage is divided into consecutive windows split at scene and activity boundaries, so an event does not land across a seam.',
    detail: 'Roughly 15-25s per window.',
  },
  {
    title: 'Extraction',
    body: 'Each window produces four independent signals. They are never averaged or concatenated into one vector, because collapsing them loses the ability to say which modality matched.',
    detail: 'Visual (X-CLIP) · Audio events (CLAP) · Transcript (Whisper then BGE-M3) · Caption (Qwen2.5-VL or Gemini)',
  },
  {
    title: 'Indexing',
    body: 'Windows are written as separate named vectors per modality, alongside timestamps, transcript, caption, objects, and actions.',
    detail: 'visual · audio_event · speech_text · vlm_text',
  },
  {
    title: 'Query understanding',
    body: 'A request arrives as text, speech, a reference image, a reference clip, or any combination. Spoken requests go to the model as audio; nothing transcribes them first.',
    detail: 'All modalities travel in a single request.',
  },
  {
    title: 'Retrieval and fusion',
    body: 'Each modality retrieves its own candidates, then reciprocal-rank fusion merges them. Fusion is by rank, not by raw score, so a modality that is absent contributes no rank instead of a misleading zero.',
    detail: 'This is what keeps a silent video from being penalised.',
  },
  {
    title: 'Localisation',
    body: 'Overlapping windows are deduplicated, the strongest sections are kept, and each is cut with ffmpeg into a playable clip.',
    detail: 'Ranges are clamped to the real duration before cutting.',
  },
]

export function HowItWorks() {
  const [language] = useLanguage()
  const t = stringsFor(language)
  return (
    <PageShell heroHeight="55vh">
      <div className="mx-auto w-full max-w-3xl px-6 pb-24 pt-8">
        <h1
          className="text-5xl leading-tight tracking-tight text-white md:text-6xl"
          style={{ fontFamily: "'Instrument Serif', serif" }}
        >
          {t.howTitle} <span className="italic text-glow">{t.howEmphasis}</span>
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-white/70">
          {t.howSubtitle}
        </p>

        <div className="mt-12 space-y-4">
          {STAGES.map((stage, index) => (
            <section
              key={stage.title}
              className="liquid-glass rounded-2xl border border-white/10 bg-ink-900/70 p-5"
            >
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-xs text-glow">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <h2 className="text-lg text-paper-100">{stage.title}</h2>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-paper-300/75">{stage.body}</p>
              <p className="mt-3 font-mono text-[11px] leading-relaxed text-paper-300/40">
                {stage.detail}
              </p>
            </section>
          ))}
        </div>
      </div>
    </PageShell>
  )
}
