/**
 * §8.1a's `fetch` route, with a person on it — *"the calling agent looks at the page"*.
 *
 * Every other move this console makes delegates the looking: the runner cannot see a raster, so
 * it pays a sub-model to (§8.1a, `runner/route.py::caller`). Here the raster is on the left of
 * the screen and an operator is reading it, which is the one case where the free route is
 * literally available — and it is the only move in the product that a person can make and the
 * machine cannot.
 *
 * **It is not a way around the gate; it is the gate's other input.** A draft that arrives
 * already written skipped Correction Loop 1 — the per-code stamp that lives inside `read` — so
 * nothing has checked a single code in it. `POST /ask` runs the identical server-side gate over
 * it, per `(claim, page)`, and §8.4 does not ask which route produced the draft. What comes back
 * is a badged answer, or a rejection of the whole thing.
 *
 * Two consequences worth stating, because they are what the operator is actually buying:
 *
 *   * on a page whose text extracted cleanly, a code they read off the picture comes back
 *     `verified` — the page's own text prints it, and now somebody has checked that;
 *   * **on an image-only page nothing can check it**, so it renders with the *read from image,
 *     not text-verified* badge and the answer carries the amber warning. That is the honest
 *     outcome R2 is about, and it is the only way this corpus can produce one: a scan has no
 *     text layer to verify against, and saying *"that code is not on the page"* about a page
 *     nobody could read turns our blind spot into the reader's confident denial.
 *
 * It spends nothing. `reads` is `0` on this route and the budget is untouched (§7.2.5).
 */
import { useState } from 'react'

export interface ReadOffProps {
  /** The page the draft is written from and every code in it is checked against. */
  pageId: string
  /** The question the draft answers. `POST /ask` requires one; the gate records it. */
  question: string
  pending: boolean
  onSubmit: (text: string) => void
}

export function ReadOff({ pageId, question, pending, onSubmit }: ReadOffProps) {
  const [text, setText] = useState('')
  const ready = question.trim() !== '' && text.trim() !== '' && !pending

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!ready) return
    onSubmit(text.trim())
  }

  return (
    <form className="panel read-off" data-testid="read-off" data-page-id={pageId} onSubmit={submit}>
      <h2 className="panel-head">
        what do you read on this page?
        <span className="faint">checked before it renders</span>
      </h2>
      <div className="panel-body">
        <textarea
          className="read-off-text"
          rows={3}
          aria-label="what you read on this page"
          data-testid="read-off-text"
          placeholder="Write what this page says, in your words. Every code in it is checked against this page before any of it is shown."
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <div className="read-off-actions">
          <button type="submit" data-testid="read-off-submit" disabled={!ready}>
            {pending ? 'checking…' : 'check and render'}
          </button>
          {question.trim() === '' ? (
            <span className="card-meta" data-testid="read-off-needs-question">
              Ask a question first — a draft is an answer to one, and the gate records which.
            </span>
          ) : (
            <span className="card-meta">
              Nothing is spent on this route: you looked, so no model is paid to (§8.1a).
            </span>
          )}
        </div>
      </div>
    </form>
  )
}
