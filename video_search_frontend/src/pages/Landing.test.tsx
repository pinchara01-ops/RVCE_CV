import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Landing } from './Landing'
import { getPublicSamples, getPublicUsage, runQuickSearch } from '../lib/api'

vi.mock('../components/BackgroundVideo', () => ({ BackgroundVideo: () => <div /> }))
vi.mock('../components/ParticleField', () => ({ ParticleField: () => <div /> }))
vi.mock('../components/StageSequence', () => ({ StageSequence: () => <div>Searching</div> }))
vi.mock('../lib/analytics', () => ({ track: vi.fn() }))
vi.mock('../lib/api', async (original) => {
  const actual = await original<typeof import('../lib/api')>()
  return {
    ...actual,
    getPublicSamples: vi.fn(),
    getPublicUsage: vi.fn(),
    runQuickSearch: vi.fn(),
  }
})

const samples = [{
  id: 'animal-belly-rub', name: 'Animals enjoying belly rubs', description: 'Playful animal footage.',
  duration: '3:01', modalities: ['video', 'audio'], available: true,
  queries: ['Find the moment a dog gets a belly rub.'],
}]

describe('public launch landing page', () => {
  beforeEach(() => {
    vi.mocked(getPublicSamples).mockResolvedValue(samples)
    vi.mocked(getPublicUsage).mockResolvedValue({ limit: 2, remaining: 2, resetAt: '2026-08-10T00:00:00Z' })
    vi.mocked(runQuickSearch).mockReset()
    window.history.replaceState({}, '', '/')
  })

  it('opens directly on the usable demo without model or API-key onboarding', async () => {
    render(<Landing />)
    expect(screen.getByRole('heading', { name: /Search any video archive/i })).toBeInTheDocument()
    expect(screen.queryByText(/choose a deployment profile/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/paste an api key/i)).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /Animals enjoying belly rubs/i })).toBeInTheDocument()
    expect(screen.getByText(/2 free live searches remaining today/i)).toBeInTheDocument()
  })

  it('fills a suggested query without starting a paid search', async () => {
    render(<Landing />)
    expect(screen.queryByRole('textbox', { name: /describe the moment/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/exact matching moments/i)).not.toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /Animals enjoying belly rubs/i }))
    expect(screen.queryByText(/choose a video on the left/i)).not.toBeInTheDocument()
    expect(screen.getByText(/selected:/i)).toBeInTheDocument()
    const suggestion = await screen.findByRole('button', { name: 'Find the moment a dog gets a belly rub.' })
    fireEvent.click(suggestion)
    await waitFor(() => expect(screen.getByRole('textbox', { name: /describe the moment/i })).toHaveValue('Find the moment a dog gets a belly rub.'))
    expect(runQuickSearch).not.toHaveBeenCalled()
  })

  it('lets a visitor choose one personal video and submit it for live search', async () => {
    vi.mocked(runQuickSearch).mockResolvedValue({
      request_id: 'request-1', query: 'find the dog', spoken: false,
      summary: 'No matching moments.', model: 'gemini', moments: [],
      usage: { limit: 2, remaining: 1, resetAt: '2026-08-10T00:00:00Z' },
    })
    render(<Landing />)
    fireEvent.click(await screen.findByRole('button', { name: /Upload yours/i }))
    expect(screen.queryByRole('textbox', { name: /Describe the moment/i })).not.toBeInTheDocument()
    const file = new File(['video'], 'my-clip.webm', { type: 'video/webm' })
    fireEvent.change(screen.getByLabelText(/^Choose one video file/i), { target: { files: [file] } })
    fireEvent.change(screen.getByRole('textbox', { name: /Describe the moment/i }), { target: { value: 'find the dog' } })
    fireEvent.click(screen.getByRole('button', { name: /Run search/i }))

    await waitFor(() => expect(runQuickSearch).toHaveBeenCalled())
    expect(vi.mocked(runQuickSearch).mock.calls[0][1]).toBe(file)
  })
})
