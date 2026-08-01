import './ResultRow.css'

const MODALITY_STYLE = {
  visual: 'tag--mustard',
  audio: 'tag--olive',
  speech: 'tag--rust',
  caption: 'tag--neutral',
}

function formatTimestamp(seconds) {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

// The backend only ever gives us a window's own start/end, not the full
// source clip's length - there's no "total duration" field in the
// contract. This derives a plausible-looking total so the timeline bar
// has something sensible to place the highlighted segment within,
// deterministic per window_id so it doesn't jitter on re-render.
function pseudoClipDuration(windowId, end) {
  let hash = 0
  for (let i = 0; i < windowId.length; i++) {
    hash = (hash * 31 + windowId.charCodeAt(i)) >>> 0
  }
  const padding = 40 + (hash % 400)
  return end + padding
}

export default function ResultRow({ result }) {
  const { video_id, window_id, start, end, caption, transcript, score, matched_modalities } = result
  const clipDuration = pseudoClipDuration(window_id, end)
  const segmentLeft = (start / clipDuration) * 100
  const segmentWidth = Math.max(((end - start) / clipDuration) * 100, 2)

  return (
    <div className="result-row">
      <div className="result-row__thumb">
        <div className="result-row__thumb-pattern" aria-hidden="true" />
        <div className="result-row__timeline">
          <div
            className="result-row__timeline-segment"
            style={{ left: `${segmentLeft}%`, width: `${segmentWidth}%` }}
          />
        </div>
      </div>

      <div className="result-row__body">
        <div className="result-row__meta-line">
          <span className="result-row__video-id font-mono">{video_id}</span>
          <span className="result-row__timestamp font-mono">
            {formatTimestamp(start)} – {formatTimestamp(end)}
          </span>
        </div>

        <p className="result-row__caption">{caption}</p>

        {transcript && <p className="result-row__transcript font-mono">“{transcript}”</p>}

        <div className="result-row__tags">
          {matched_modalities.map((m) => (
            <span key={m} className={`tag ${MODALITY_STYLE[m] ?? 'tag--neutral'}`}>
              {m}
            </span>
          ))}
          <span className="result-row__score font-mono">{score.toFixed(4)}</span>
        </div>
      </div>
    </div>
  )
}
