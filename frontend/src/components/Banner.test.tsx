/**
 * An outage on screen.
 *
 * §7.1's rule — *"a backend failure is a 5xx, never an empty result"* — has a far end, and this
 * is it. The listed edge case for this unit is *"a `503` from the backend (a banner, never a
 * blank page)"*, because a console that renders an outage as an empty list tells an operator the
 * corpus holds nothing. That is the same confusion the four typed absences exist to prevent, one
 * layer up, and it is the most expensive lie this system could tell.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import { Banner, Notice } from './Banner.tsx'
import { ApiError } from '../api/client.ts'

afterEach(cleanup)

describe('Banner', () => {
  it('renders nothing when there is no error — it is not a permanent chrome element', () => {
    const { container } = render(<Banner error={null} />)
    expect(container.innerHTML).toBe('')
  })

  it('names the service’s own error code rather than a generic failure', () => {
    render(
      <Banner
        error={new ApiError(503, { error: 'qdrant_unavailable', detail: 'the index is down', retryable: true })}
      />,
    )
    const banner = screen.getByTestId('error-banner')
    expect(banner.getAttribute('data-code')).toBe('qdrant_unavailable')
    expect(banner.textContent).toContain('the index is down')
  })

  it('is announced, so it is not a silent colour change', () => {
    render(<Banner error={new ApiError(503, { error: 'qdrant_unavailable', detail: 'down' })} />)
    expect(screen.getByRole('alert')).toBeTruthy()
  })

  it('says when the service called the failure retryable (§11.3)', () => {
    render(
      <Banner error={new ApiError(503, { error: 'vlm_unavailable', detail: 'down', retryable: true })} />,
    )
    expect(screen.getByTestId('error-banner').textContent).toContain('worth retrying')
  })

  it('does not invite a retry on a typed refusal, which is a decision and not flakiness', () => {
    render(
      <Banner error={new ApiError(400, { error: 'dpi_requires_region', detail: 'pass a region' })} />,
    )
    expect(screen.getByTestId('error-banner').textContent).not.toContain('worth retrying')
  })

  it('falls back to the code when the service sent no detail', () => {
    render(<Banner error={new ApiError(500, { error: 'internal', detail: '' })} />)
    expect(screen.getByTestId('error-banner').textContent).toContain('internal')
  })
})

describe('Notice', () => {
  it('is amber and advisory — a disclosure, not a failure', () => {
    render(<Notice testId="a-notice">read from the page image</Notice>)
    const notice = screen.getByTestId('a-notice')
    expect(notice.getAttribute('data-tone')).toBe('warn')
    expect(notice.getAttribute('role')).toBe('note')
  })
})
