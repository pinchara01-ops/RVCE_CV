import { useEffect, useRef, useState } from 'react'

const BAR_COUNT = 48
const SAMPLE_MS = 60

export interface Recording {
  blob: Blob
  peaks: number[]
  seconds: number
}

type RecorderState = 'idle' | 'recording'

interface UseRecorderResult {
  state: RecorderState
  livePeaks: number[]
  start: () => Promise<void>
  stop: () => void
}

/**
 * Microphone capture with an amplitude trace for display.
 *
 * The peak trace is collected while recording so the frozen waveform shown
 * afterwards is the real envelope of what was captured, not a decorative
 * animation replayed from nothing.
 */
export function useRecorder(
  onRecorded: (recording: Recording) => void,
  onError: (message: string) => void,
): UseRecorderResult {
  const [state, setState] = useState<RecorderState>('idle')
  const [livePeaks, setLivePeaks] = useState<number[]>([])

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const peaksRef = useRef<number[]>([])
  const rafRef = useRef<number | undefined>(undefined)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const startedAtRef = useRef(0)

  const cleanup = () => {
    if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current)
    rafRef.current = undefined
    void audioCtxRef.current?.close().catch(() => undefined)
    audioCtxRef.current = null
  }

  useEffect(() => {
    return () => {
      const recorder = recorderRef.current
      if (recorder && recorder.state !== 'inactive') recorder.stop()
      recorder?.stream.getTracks().forEach((track) => track.stop())
      cleanup()
    }
  }, [])

  const start = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      onError('This browser cannot record audio.')
      return
    }

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      onError('Microphone access was blocked. Allow it in the browser, then try again.')
      return
    }

    chunksRef.current = []
    peaksRef.current = []
    setLivePeaks([])
    startedAtRef.current = performance.now()

    const ctx = new AudioContext()
    audioCtxRef.current = ctx
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    ctx.createMediaStreamSource(stream).connect(analyser)
    const buffer = new Uint8Array(analyser.frequencyBinCount)

    let lastSample = 0
    const tick = () => {
      analyser.getByteTimeDomainData(buffer)
      const now = performance.now()
      if (now - lastSample >= SAMPLE_MS) {
        lastSample = now
        // Peak deviation from silence (128), normalised to 0..1.
        let peak = 0
        for (let i = 0; i < buffer.length; i++) {
          const value = Math.abs(buffer[i] - 128) / 128
          if (value > peak) peak = value
        }
        peaksRef.current.push(Math.min(1, peak * 1.6))
        setLivePeaks([...peaksRef.current])
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    const recorder = new MediaRecorder(stream)
    recorderRef.current = recorder
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data)
    }
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop())
      cleanup()
      setState('idle')

      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
      if (!blob.size) {
        onError('Nothing was recorded. Try again.')
        return
      }
      onRecorded({
        blob,
        peaks: peaksRef.current.slice(),
        seconds: (performance.now() - startedAtRef.current) / 1000,
      })
    }

    recorder.start()
    setState('recording')
  }

  const stop = () => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') recorder.stop()
  }

  return { state, livePeaks, start, stop }
}

interface WaveformProps {
  peaks: number[]
  live: boolean
}

/**
 * Bar-graph waveform. While live it scrolls to show the most recent window;
 * once frozen it resamples the whole recording so the full shape stays visible.
 */
export function Waveform({ peaks, live }: WaveformProps) {
  let bars: number[]
  if (!peaks.length) {
    bars = new Array(BAR_COUNT).fill(0)
  } else if (live) {
    const recent = peaks.slice(-BAR_COUNT)
    bars = [...new Array(Math.max(0, BAR_COUNT - recent.length)).fill(0), ...recent]
  } else {
    // Resample the whole capture down to a fixed bar count.
    bars = Array.from({ length: BAR_COUNT }, (_, index) => {
      const from = Math.floor((index * peaks.length) / BAR_COUNT)
      const to = Math.max(from + 1, Math.floor(((index + 1) * peaks.length) / BAR_COUNT))
      let peak = 0
      for (let i = from; i < to && i < peaks.length; i++) peak = Math.max(peak, peaks[i])
      return peak
    })
  }

  return (
    <div className="flex h-8 flex-1 items-center gap-[2px]" aria-hidden="true">
      {bars.map((value, index) => (
        <div
          key={index}
          className={`flex-1 rounded-full transition-[height] duration-75 ${
            live ? 'bg-red-400' : 'bg-glow'
          }`}
          style={{ height: `${Math.max(6, value * 100)}%`, opacity: value > 0.02 ? 1 : 0.35 }}
        />
      ))}
    </div>
  )
}
