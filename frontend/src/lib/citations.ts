/**
 * Clicking a code in the draft, and the page it reaches — §13 M7's last sentence.
 *
 * The gesture matters more than it looks. A badge says *"this code was checked against the page
 * it is cited on"*, and the only way a reader can audit that sentence is to see **that** page.
 * So the click does not scroll to the first citation or to the page the answer opened on: it
 * scrolls to `claim.page_id`, the page the check was actually made against, which is the page
 * whose raster either does or does not print the code.
 *
 * Kept as pure functions over ids so it is testable without a DOM: a component turns the selected
 * id into a scroll, and this module decides *which* id.
 */
import type { Answer, Check, RenderedClaim } from '../api/types.ts'

/** The pages the viewer offers, in look order, with no duplicates. */
export function citedPages(answer: Answer | null): string[] {
  if (answer === null) return []
  const seen = new Set<string>()
  const ordered: string[] = []
  for (const pageId of [...answer.citations, ...answer.claims.map((claim) => claim.page_id)]) {
    if (pageId && !seen.has(pageId)) {
      seen.add(pageId)
      ordered.push(pageId)
    }
  }
  return ordered
}

/**
 * The page a click on this claim should reach: **the page it is cited on**, and never a fallback.
 *
 * A claim whose `page_id` is not among the citations is still followed there — the citation list
 * is the pages the draft was written from, and the gate checked the claim against the page the
 * claim named. Scrolling somewhere else to keep the viewer tidy would show a reader a page the
 * badge is not about.
 */
export function targetPage(claim: RenderedClaim): string {
  return claim.page_id
}

/** The gate's rows for one claim — the calls behind its badge, so a reader can audit it. */
export function checksFor(claim: RenderedClaim, checks: readonly Check[]): Check[] {
  return checks.filter((row) => row.claim === claim.code && row.page_id === claim.page_id)
}

/**
 * The rejections in the call log: rows whose verdict was `absent`, with the claim redacted.
 *
 * §8.4 keeps the row auditable and drops the code, and this is the honest way to show that — the
 * console reports *"one check on this page came back `absent`"* and cannot report which code,
 * because it was never sent one. A UI that guessed the code from the draft would put the rejected
 * string back on screen, which is the one thing the redaction exists to prevent.
 */
export function rejectedChecks(checks: readonly Check[]): Check[] {
  return checks.filter((row) => row.status === 'absent')
}

/**
 * The codes that appear in the draft's prose but are **not** rendered claims.
 *
 * Always empty on a cleared answer, and that is worth asserting rather than assuming: the gate
 * checks the union of the declared claims and the codes in the text (§8.4), so a code in the
 * prose with no badge beside it would mean something reached the reader unchecked.
 */
export function unbadgedCodes(answer: Answer | null, codeLike: RegExp = CODE_LIKE): string[] {
  if (answer === null) return []
  const badged = new Set(answer.claims.map((claim) => claim.code))
  const found = answer.text.match(codeLike) ?? []
  return [...new Set(found.filter((code) => !badged.has(code)))]
}

/**
 * A code-shaped token, for the audit above only.
 *
 * Deliberately **not** an identifier grammar: §2.4 struck `impl`'s, and this app is not permitted
 * to hold one — it decides nothing and matches nothing. It exists so the console can notice a
 * badge-less code and say so, and a false positive here is a visible warning rather than a
 * silent claim.
 */
export const CODE_LIKE = /\b[A-Z]{1,3}[0-9]{2,4}\b/g
