// Mock results shaped exactly like the real backend's response contract
// (query_retrieval/models.py: SearchResponse -> SearchResultItem), so
// swapping searchApi.js over to the real POST /search endpoint is a
// drop-in replacement, not a rewrite. See src/api/searchApi.js.

export const MOCK_RESULTS = [
  {
    video_id: 'cam03_northgate',
    window_id: 'cam03_northgate_window_0014',
    start: 182.4,
    end: 191.2,
    caption: 'A person in a dark jacket approaches the side entrance and pauses near the door.',
    transcript: '',
    score: 0.0871,
    matched_modalities: ['visual', 'caption'],
  },
  {
    video_id: 'cam01_lobby',
    window_id: 'cam01_lobby_window_0032',
    start: 45.0,
    end: 52.5,
    caption: 'Two people cross the lobby near the front desk.',
    transcript: 'someone says thanks, see you tomorrow',
    score: 0.0742,
    matched_modalities: ['visual', 'speech', 'caption'],
  },
  {
    video_id: 'cam06_loadingdock',
    window_id: 'cam06_loadingdock_window_0007',
    start: 903.1,
    end: 911.8,
    caption: 'A metallic crash near the loading dock, followed by raised voices.',
    transcript: 'hey, watch where you are going with that',
    score: 0.0688,
    matched_modalities: ['audio', 'speech'],
  },
  {
    video_id: 'cam02_parking',
    window_id: 'cam02_parking_window_0021',
    start: 1204.6,
    end: 1219.0,
    caption: 'A vehicle pulls into the far corner of the parking area and idles.',
    transcript: '',
    score: 0.0553,
    matched_modalities: ['visual'],
  },
  {
    video_id: 'cam04_backdoor',
    window_id: 'cam04_backdoor_window_0045',
    start: 66.2,
    end: 71.4,
    caption: 'A dog barks somewhere off-frame near the back door.',
    transcript: '',
    score: 0.0417,
    matched_modalities: ['audio'],
  },
  {
    video_id: 'cam05_hallway',
    window_id: 'cam05_hallway_window_0003',
    start: 12.0,
    end: 18.6,
    caption: 'An empty hallway, motion-triggered by a passing shadow.',
    transcript: '',
    score: 0.0309,
    matched_modalities: ['caption'],
  },
]
