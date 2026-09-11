/**
 * §8.1a's `fetch` route, from the console's side.
 *
 * The assertions here are about what the form **will not do**, because that is what makes the
 * route safe to offer at all: it cannot submit without a question (the gate records which one
 * was asked), it cannot submit an empty draft, and it declares **no claims** — the gate
 * re-derives them from the prose and checks the union, so a code the operator typed cannot
 * escape a check by not having been listed (§8.4).
 *
 * What happens to the draft after that is the server's, and `tests/api/test_ask_replay.py`
 * already holds it to I8 on both routes. What this file proves is that the console hands the
 * gate the whole of what a person wrote, and that the page it cites is the page on screen.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { ReadOff } from './ReadOff.tsx'

afterEach(cleanup)

const PAGE = 'vsir-raster@1.0#p001'

/** `hasAttribute`, the way the rest of this suite reads a disabled control. */
function disabled(testId: string): boolean {
  return screen.getByTestId(testId).hasAttribute('disabled')
}

function draw(question: string, onSubmit = vi.fn(), pending = false) {
  render(<ReadOff pageId={PAGE} question={question} pending={pending} onSubmit={onSubmit} />)
  return onSubmit
}

describe('the operator draft', () => {
  it('cannot be submitted with no question, and says why', () => {
    draw('')
    expect(disabled('read-off-submit')).toBe(true)
    expect(screen.getByTestId('read-off-needs-question')).toBeTruthy()
  })

  it('cannot be submitted empty', () => {
    draw('what does the cover sheet name')
    expect(disabled('read-off-submit')).toBe(true)
    fireEvent.change(screen.getByTestId('read-off-text'), { target: { value: '   ' } })
    expect(disabled('read-off-submit')).toBe(true)
  })

  it('submits what was typed, trimmed, for the page on screen', () => {
    const onSubmit = draw('what does the cover sheet name')
    fireEvent.change(screen.getByTestId('read-off-text'),
                     { target: { value: '  The cover sheet names C24.  ' } })
    fireEvent.click(screen.getByTestId('read-off-submit'))

    expect(onSubmit).toHaveBeenCalledWith('The cover sheet names C24.')
    expect(screen.getByTestId('read-off').getAttribute('data-page-id')).toBe(PAGE)
  })

  it('is inert while a call is in flight — one question, one gate run', () => {
    const onSubmit = draw('what does the cover sheet name', vi.fn(), true)
    fireEvent.change(screen.getByTestId('read-off-text'), { target: { value: 'C24' } })
    expect(disabled('read-off-submit')).toBe(true)
    fireEvent.submit(screen.getByTestId('read-off'))
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
