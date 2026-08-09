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
  id: 'atm-surveillance', name: 'ATM surveillance', description: 'Fixed-camera footage.',
  duration: '1:15', modalities: ['video', 'audio'], available: true,
  queries: ['Show the moment someone approaches the ATM.'],
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
    expect(await screen.findByRole('button', { name: /ATM surveillance/i })).toBeInTheDocument()
    expect(screen.getByText(/2 free live searches remaining today/i)).toBeInTheDocument()
  })

  it('fills a suggested query without starting a paid search', async () => {
    render(<Landing />)
    const suggestion = await screen.findByRole('button', { name: 'Show the moment someone approaches the ATM.' })
    fireEvent.click(suggestion)
    await waitFor(() => expect(screen.getByRole('textbox', { name: /search your footage/i })).toHaveValue('Show the moment someone approaches the ATM.'))
    expect(runQuickSearch).not.toHaveBeenCalled()
  })
})
