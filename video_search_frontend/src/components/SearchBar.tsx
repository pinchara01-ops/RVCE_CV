import { useEffect, useState } from 'react'
import { ArrowRight, Mic, Square, X } from 'lucide-react'
import { useRecorder, Waveform, type Recording } from './VoiceRecorder'

const EXAMPLE_QUERIES = [
  'a person opening a red door at night',
  'व्यक्ति दरवाज़ा खोलता है',
  'ಒಬ್ಬ ವ್ಯಕ್ತಿ ರಾತ್ರಿ ಕೆಂಪು ಬಾಗಿಲು ತೆರೆಯುತ್ತಿದ್ದಾನೆ',
]

interface SearchBarProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled: boolean
  recording: Recording | null
  onRecorded: (recording: Recording | null) => void
  onVoiceError?: (message: string) => void
}

export function SearchBar({
  value,
  onChange,
  onSubmit,
  disabled,
  recording,
  onRecorded,
  onVoiceError,
}: SearchBarProps) {
  const [placeholderIndex, setPlaceholderIndex] = useState(0)
  const [fade, setFade] = useState(true)

  const { state, livePeaks, start, stop } = useRecorder(onRecorded, (message) =>
    onVoiceError?.(message),
  )
  const isRecording = state === 'recording'

  useEffect(() => {
    const interval = setInterval(() => {
      setFade(false)
      const timeout = setTimeout(() => {
        setPlaceholderIndex((i) => (i + 1) % EXAMPLE_QUERIES.length)
        setFade(true)
      }, 250)
      return () => clearTimeout(timeout)
    }, 3200)
    return () => clearInterval(interval)
  }, [])

  const canSubmit = !disabled && (Boolean(value.trim()) || Boolean(recording))

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (canSubmit) onSubmit()
      }}
      className="liquid-glass mx-auto flex w-full max-w-xl items-center gap-3 rounded-full py-2 pl-6 pr-2"
    >
      {isRecording ? (
        <>
          <Waveform peaks={livePeaks} live />
          <span className="shrink-0 font-mono text-xs text-red-300">rec</span>
        </>
      ) : recording ? (
        <>
          <Waveform peaks={recording.peaks} live={false} />
          <span className="shrink-0 font-mono text-xs text-paper-300/50">
            {recording.seconds.toFixed(1)}s
          </span>
          <button
            type="button"
            onClick={() => onRecorded(null)}
            disabled={disabled}
            aria-label="Discard recording"
            className="shrink-0 rounded-full p-2 text-white/60 transition-colors hover:text-white disabled:opacity-40"
          >
            <X size={16} />
          </button>
        </>
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={EXAMPLE_QUERIES[placeholderIndex]}
          disabled={disabled}
          className={`min-w-0 flex-1 bg-transparent text-base text-white outline-none placeholder:text-white/40 placeholder:transition-opacity placeholder:duration-300 ${
            fade ? 'placeholder:opacity-100' : 'placeholder:opacity-0'
          }`}
          aria-label="Search your footage"
        />
      )}

      {!recording && (
        <button
          type="button"
          onClick={isRecording ? stop : () => void start()}
          disabled={disabled}
          aria-label={isRecording ? 'Stop recording' : 'Ask by voice'}
          title={isRecording ? 'Stop recording' : 'Ask by voice'}
          className={`flex shrink-0 items-center justify-center rounded-full p-3 transition-colors disabled:opacity-40 ${
            isRecording ? 'bg-red-500/90 text-white' : 'bg-white/10 text-white hover:bg-white/20'
          }`}
        >
          {isRecording ? <Square size={18} fill="currentColor" /> : <Mic size={18} />}
        </button>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="flex shrink-0 items-center justify-center rounded-full bg-white p-3 text-black transition-opacity disabled:opacity-40"
        aria-label="Run search"
      >
        <ArrowRight size={20} />
      </button>
    </form>
  )
}
