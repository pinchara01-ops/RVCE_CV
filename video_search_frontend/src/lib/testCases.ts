// Edge-case corpus for the architecture.
//
// The files below are REAL and present in the repository under
// test_assets/asset_library/. They are derived with ffmpeg from the two
// licensed originals in that library (see its manifest.json for provenance and
// licence), so nothing here depends on an external download.
//
// PLACEHOLDER METRICS
// `accuracy`, `recall`, and `latencySeconds` are PLACEHOLDER values. None of
// these cases has been run end-to-end yet. Replace each number with a real
// figure and flip `verified` to true once that case has actually been run.
//
// The `challenge` / `mitigation` text describes behaviour that IS in the code
// today (duration probing and clamping, per-container MIME mapping, WebM to MP3
// transcoding, native-audio routing, rank-based fusion). Do not add a fix here
// that does not exist in the codebase.

export interface TestCase {
  id: string
  title: string
  /** Which architectural assumption this case stresses. */
  stresses: string
  /** Path under test_assets/asset_library/. */
  localFile: string
  durationSeconds: number
  /** Streams actually present in the file. */
  streams: string
  query: string
  challenge: string
  mitigation: string
  /** The section this case is about, played after "Try it out". */
  sectionStart: number
  sectionEnd: number
  accuracy: number
  recall: number
  latencySeconds: number
  verified: boolean
}

export const ASSET_ROOT = 'test_assets/asset_library/media'

export const TEST_CASES: TestCase[] = [
  {
    id: 'silent-video',

    title: 'Video with no audio track',
    stresses: 'Audio and speech channels are empty; retrieval must fall back to visual only.',
    localFile: 'derived/atm_silent.mp4',
    durationSeconds: 74.7,
    streams: 'video only',
    query: 'people breaking open a machine',
    challenge:
      'With no audio track the speech and audio-event channels return nothing. A fusion that averages across modalities dilutes the visual score with two empty channels and pushes real matches down the ranking.',
    mitigation:
      'Modalities stay in independent named vectors and are fused by rank, never by averaging raw scores, so an absent channel contributes no rank rather than a zero score.',
    sectionStart: 35.5,
    sectionEnd: 41.5,
    accuracy: 86,
    recall: 84,
    latencySeconds: 11.4,
    verified: false,
  },
  {
    id: 'audio-only',

    title: 'Audio-only file, no video stream',
    stresses: 'Visual channel is absent; the pipeline must not assume frames exist.',
    localFile: 'derived/atm_audio_only.mp3',
    durationSeconds: 74.7,
    streams: 'audio only',
    query: 'loud banging and metal being struck',
    challenge:
      'Frame sampling and duration probing both assume a video stream. Reading duration from the video stream returns nothing for an audio-only input, which leaves returned timestamps unbounded.',
    mitigation:
      'Duration is probed from the container format rather than the video stream, so it resolves for audio-only inputs, and every returned range is clamped to it before clipping.',
    sectionStart: 35.0,
    sectionEnd: 42.0,
    accuracy: 88,
    recall: 85,
    latencySeconds: 7.2,
    verified: false,
  },
  {
    id: 'mismatched-audio',

    title: 'Audio completely unrelated to the video',
    stresses: 'Cross-modal contradiction; audio must not invent visual events.',
    localFile: 'derived/atm_mismatched_audio.mp4',
    durationSeconds: 74.0,
    streams: 'video + unrelated audio',
    query: 'a traffic stop by the roadside',
    challenge:
      'This file pairs indoor ATM footage with dashcam audio from a roadside incident. A captioner reading both channels together will describe events the footage never shows, producing confident but ungrounded matches.',
    mitigation:
      'The caption prompt constrains descriptions to visible evidence only and forbids inferring audio, intent, or events outside the clip, so the visual channel is not overridden by the soundtrack.',
    sectionStart: 2.5,
    sectionEnd: 9.0,
    accuracy: 83,
    recall: 80,
    latencySeconds: 12.8,
    verified: false,
  },
  {
    id: 'webm-vp9',

    title: 'WebM / VP9 + Opus container',
    stresses: 'Container support: not every format is accepted directly by the provider.',
    localFile: 'derived/dashcam_45s.webm',
    durationSeconds: 45.0,
    streams: 'vp9 video + opus audio',
    query: 'a vehicle on the road ahead',
    challenge:
      'WebM is not accepted by every provider model, and browser microphone capture also produces WebM/Opus, so an unconverted upload fails with an opaque provider error rather than a useful message.',
    mitigation:
      'Video MIME types are mapped per container so WebM is declared correctly, and recorded audio is transcoded to MP3 with ffmpeg before the call.',
    sectionStart: 10.0,
    sectionEnd: 18.0,
    accuracy: 90,
    recall: 88,
    latencySeconds: 13.1,
    verified: false,
  },
  {
    id: 'long-form',

    title: 'Long-form footage, 20 minutes',
    stresses: 'Temporal drift over long durations.',
    localFile: 'public_domain/ga_paulding_vehicle_burglary_dashcam_20m.webm',
    durationSeconds: 1200.0,
    streams: 'vp9 video + opus audio',
    query: 'a vehicle pulling over',
    challenge:
      'Over long durations the model estimates elapsed time from sampled frames, and that estimate drifts. It returned start and end timestamps past the end of the file, which produced ranges that could not be cut into clips.',
    mitigation:
      'The exact duration is probed with ffprobe and stated in the prompt, and returned ranges are clamped server-side: trailing overhang is trimmed, ranges starting past the end are dropped, and sub-0.3s slivers are discarded.',
    sectionStart: 120.0,
    sectionEnd: 128.0,
    accuracy: 81,
    recall: 78,
    latencySeconds: 46.5,
    verified: false,
  },
  {
    id: 'low-light',

    title: 'Low-light footage',
    stresses: 'Visual embedding quality under poor illumination.',
    localFile: 'derived/atm_low_light.mp4',
    durationSeconds: 74.7,
    streams: 'darkened video + audio',
    query: 'movement inside a dark room',
    challenge:
      'Low-contrast frames compress the visual embedding space, so distinct scenes sit close together and the visual channel loses discriminative power.',
    mitigation:
      'Ranked fusion lets the audio and speech channels carry the result when the visual channel degrades, instead of a single weak modality deciding the outcome.',
    sectionStart: 35.5,
    sectionEnd: 41.5,
    accuracy: 79,
    recall: 76,
    latencySeconds: 12.2,
    verified: false,
  },
  {
    id: 'no-match',

    title: 'Query with no valid answer in the footage',
    stresses: 'Negative case: the system must decline rather than force a match.',
    localFile: 'public_domain/vidssave.com Surveillance_ Thieves rip open ATM in Shelbyville 1080P.mp4',
    durationSeconds: 74.7,
    streams: 'h264 video + aac audio',
    query: 'an elephant crossing a motorway',
    challenge:
      'Ranked retrieval always returns a top-k, so a query with no true answer still surfaces a best-of-a-bad-set result that reads as a confident match.',
    mitigation:
      'The prompt requires an empty result set when nothing matches, and the response says so in the summary rather than returning a low-confidence moment.',
    sectionStart: 0.0,
    sectionEnd: 6.0,
    accuracy: 92,
    recall: 90,
    latencySeconds: 9.8,
    verified: false,
  },
]

export const PLACEHOLDER_NOTICE =
  'Metrics on this page are placeholders pending real runs, not measured results.'
