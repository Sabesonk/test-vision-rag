/**
 * The trust badges — §13 M7's load-bearing UI, as a pure mapping.
 *
 * This is the file the console exists for. Everything else here is plumbing; these strings are
 * what a technician reads before deciding whether to trust a code enough to act on it, and each
 * one has to say a *different* thing:
 *
 *   * **`verified`** — the code is printed in the page's own extracted text, and
 *     `ingest/probe.py` is the only writer of that text (I2). The strongest claim this system
 *     makes.
 *   * **`read from image, not text-verified`** — nobody could check it: no text layer, an
 *     untrusted extraction, or a page that is not current. The badge is the disclosure, and the
 *     wording is the service's own constant, not a paraphrase of it (`answer.BADGE_*`).
 *   * **`absent`** — never renders. A code the gate found is not on the page it is cited on
 *     rejects the whole draft (§8.4, I8), so there is no badge for it and this module returns
 *     `null`: a component that tried to render one has nothing to render.
 *
 * The same rule applies to the six-value status enum. `not_found` and `not_searchable` are two
 * different instructions — *abstain* versus *escalate to vision* — so they are two visually
 * distinct badges with two different `action` lines. Collapsing them into "no results" is the
 * failure F4 is about, one layer up in the UI.
 *
 * Colours are **tone names**, never values: a component asks for `tone` and the stylesheet turns
 * it into a CSS variable (§16 Frontend — no raw hex in a component).
 */
import {
  BADGE_READ_FROM_IMAGE,
  BADGE_VERIFIED,
  type CheckState,
  type Status,
  type TextTrust,
  type TriageMark,
  WARNING_UNVERIFIABLE,
} from '../api/types.ts'

/** The palette slot a badge is drawn in. One of these, never a colour. */
export type Tone = 'ok' | 'warn' | 'bad' | 'dim' | 'accent' | 'spend'

export interface BadgeSpec {
  /** The word on the badge. */
  label: string
  tone: Tone
  /** A stable hook for the DOM, so an E2E assertion names a state and not a colour. */
  testId: string
  /** What it means, in one line, for the operator hovering it. */
  title: string
}

// ── a rendered claim (§8.4) ─────────────────────────────────────────────────────────────────────

const VERIFIED: BadgeSpec = {
  label: BADGE_VERIFIED,
  tone: 'ok',
  testId: 'badge-verified',
  title:
    'This code is printed in the page’s own extracted text, checked against the page it is ' +
    'cited on.',
}

const READ_FROM_IMAGE: BadgeSpec = {
  label: BADGE_READ_FROM_IMAGE,
  tone: 'warn',
  testId: 'badge-read-from-image',
  title:
    'This code was read off the page image. The page has no text layer that could be checked, ' +
    'so nobody has confirmed the page prints it.',
}

/**
 * `answer.BADGE_OF`, in the browser. `absent` maps to `null` **by construction** — the union of
 * `RenderedClaim.status` does not contain it, and this function refuses it anyway so that a
 * verdict arriving from `checks` or a `read`'s stamps cannot be badged either.
 */
export function claimBadge(status: CheckState): BadgeSpec | null {
  if (status === 'present') return VERIFIED
  if (status === 'unverifiable') return READ_FROM_IMAGE
  return null
}

/** The amber warning belongs on the answer exactly when a rendered code carries the badge. */
export function warnsUnverifiable(claims: readonly { status: CheckState }[]): boolean {
  return claims.some((claim) => claim.status === 'unverifiable')
}

export const UNVERIFIABLE_WARNING = WARNING_UNVERIFIABLE

// ── the six-value status enum (§7.1) ────────────────────────────────────────────────────────────

export interface StatusSpec extends BadgeSpec {
  /** What the caller should do next. This is the whole reason there are four absences. */
  action: string
}

const STATUS: Record<Status, StatusSpec> = {
  ok: {
    label: 'ok',
    tone: 'ok',
    testId: 'status-ok',
    title: 'Searched, and something matched.',
    action: 'Read the rows.',
  },
  not_found: {
    label: 'not found',
    tone: 'dim',
    testId: 'status-not-found',
    title: 'Searched, and the searchable text of this scope holds nothing matching.',
    action: 'Abstain — unless a suggested move could still answer.',
  },
  not_searchable: {
    label: 'not searchable',
    tone: 'warn',
    testId: 'status-not-searchable',
    title: 'The candidate pages have no text layer. Nothing was searchable here.',
    action: 'Escalate to vision. Do not conclude the part does not exist.',
  },
  out_of_scope: {
    label: 'out of scope',
    tone: 'accent',
    testId: 'status-out-of-scope',
    title: 'No document matched the filters. The corpus was never asked.',
    action: 'Re-orient and widen the scope.',
  },
  found_only_in_superseded: {
    label: 'superseded only',
    tone: 'spend',
    testId: 'status-found-only-in-superseded',
    title: 'It exists, in a revision that is not current.',
    action: 'Surface the revision and decide whether it applies.',
  },
  error: {
    label: 'error',
    tone: 'bad',
    testId: 'status-error',
    title: 'The call failed. This is not an absence.',
    action: 'Retry or report — never abstain on this.',
  },
}

export function statusBadge(status: Status): StatusSpec {
  return STATUS[status] ?? STATUS.error
}

// ── the page's own text layer (§5.7) ────────────────────────────────────────────────────────────

const TRUST: Record<TextTrust, BadgeSpec> = {
  ok: { label: 'text ok', tone: 'ok', testId: 'trust-ok', title: 'A text layer that extracted cleanly.' },
  degraded: {
    label: 'text degraded',
    tone: 'warn',
    testId: 'trust-degraded',
    title: 'A text layer with problems — readable, but not clean.',
  },
  untrusted: {
    label: 'text untrusted',
    tone: 'bad',
    testId: 'trust-untrusted',
    title: 'The extraction cannot be believed. Codes on this page are unverifiable.',
  },
  no_text: {
    label: 'no text layer',
    tone: 'bad',
    testId: 'trust-no-text',
    title: 'A scan. Nothing on this page can be text-verified — this is the agent’s blind spot.',
  },
}

export function trustBadge(trust: TextTrust): BadgeSpec {
  return TRUST[trust] ?? TRUST.no_text
}

// ── triage (§8.2) ───────────────────────────────────────────────────────────────────────────────

const MARK: Record<TriageMark, BadgeSpec> = {
  relevant: {
    label: 'relevant',
    tone: 'ok',
    testId: 'mark-relevant',
    title: 'Goes to the look step.',
  },
  uncertain: {
    label: 'uncertain',
    tone: 'warn',
    testId: 'mark-uncertain',
    title: 'The pool — retained, never discarded. Drained before the scope is widened.',
  },
  irrelevant: {
    label: 'irrelevant',
    tone: 'dim',
    testId: 'mark-irrelevant',
    title: 'Excluded from the next rung. Rejected for free, before anything was spent.',
  },
}

export function markBadge(mark: TriageMark): BadgeSpec {
  return MARK[mark] ?? MARK.uncertain
}

// ── the gate's call log (§8.4) ──────────────────────────────────────────────────────────────────

/**
 * A `(claim, page)` verdict, as the **call log** renders it — three states, three badges.
 *
 * This is not `claimBadge` with the `null` filled in, and the difference is the point. A
 * *claim* may never be badged `absent`, because a draft carrying one was rejected whole and
 * nothing of it reaches a reader. A *check* may: the log keeps the row so the rejection is
 * auditable, and drops the code so the rejected string is not put back on screen (`Check.claim`
 * arrives empty). So the third badge here says a call came back `absent` without saying what was
 * asked — which is exactly what §8.4 kept and exactly what it discarded.
 *
 * `unverifiable` gets its own badge rather than borrowing the *read from image* wording. On a
 * claim that wording is the disclosure a reader acts on; in a log it is a verdict, and one word
 * per state keeps the log readable as a list of calls.
 */
const CHECK: Record<CheckState, BadgeSpec> = {
  present: {
    label: 'present',
    tone: 'ok',
    testId: 'check-present',
    title: 'The page’s own extracted text prints this code.',
  },
  absent: {
    label: 'absent',
    tone: 'bad',
    testId: 'check-absent',
    title:
      'A check on this page came back absent, and the draft it belonged to was rejected whole. ' +
      'The code is not shown: a rejection never echoes what it rejected.',
  },
  unverifiable: {
    label: 'unverifiable',
    tone: 'warn',
    testId: 'check-unverifiable',
    title:
      'Nothing could check it — no text layer, an untrusted extraction, or a page that is not ' +
      'current. Not a denial, and not a confirmation.',
  },
}

export function checkBadge(state: CheckState): BadgeSpec {
  return CHECK[state] ?? CHECK.unverifiable
}
