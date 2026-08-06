import type { SearchResponse } from './api'

// TEMPORARY DEMO DATA, used only when the real /search backend
// (query_retrieval/api.py + Qdrant) isn't reachable, so the reveal card /
// results / pipeline UI can still be tried end-to-end. Delete this file and
// its call site in api.ts once the backend is wired up for real use.
export function buildMockResponse(query: string): SearchResponse {
  return {
    results: [
      {
        video_id: 'backyard_camera_04.mp4',
        window_id: 'mock-1',
        start: 134,
        end: 149,
        transcript: '',
        caption: `A person opens a red door and steps outside at night, closest match for "${query}"`,
        score: 0.82,
        matched_modalities: ['visual', 'caption'],
        modality_evidence: [],
        source_path: '',
        media_available: false,
        source_window_ids: [],
        final_score: 0.82,
      },
      {
        video_id: 'porch_cam_01.mp4',
        window_id: 'mock-2',
        start: 58,
        end: 66,
        transcript: '',
        caption: 'Front door opening, hallway light visible behind it',
        score: 0.61,
        matched_modalities: ['visual'],
        modality_evidence: [],
        source_path: '',
        media_available: false,
        source_window_ids: [],
        final_score: 0.61,
      },
      {
        video_id: 'hallway_interior.mp4',
        window_id: 'mock-3',
        start: 302,
        end: 311,
        transcript: 'someone said the door was left open',
        caption: 'Door mentioned in nearby conversation',
        score: 0.44,
        matched_modalities: ['speech'],
        modality_evidence: [],
        source_path: '',
        media_available: false,
        source_window_ids: [],
        final_score: 0.44,
      },
    ],
    decomposition: null,
    diagnostics: {}, // empty on purpose: exercises the mocked stage-timing fallback in lib/pipeline.ts
  }
}
