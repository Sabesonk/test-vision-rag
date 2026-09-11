/**
 * A refusal, on screen — never a blank page.
 *
 * §7.1 and §11.3 are one rule in two places: *"a backend failure is a 5xx, never an empty
 * result"*. The console is the far end of that rule. A `503 qdrant_unavailable` rendered as an
 * empty list tells an operator the corpus holds nothing, which is the single most expensive lie
 * this system could tell — it is the same confusion the four typed absences exist to prevent,
 * one layer up.
 *
 * So a failed call renders the service's own `error` code and `detail`, and says whether it is
 * worth retrying, because `retryable` rides on the body of an outage refusal.
 */
import { ApiError } from '../api/client.ts'

export function Banner({ error }: { error: ApiError | null }) {
  if (error === null) return null
  return (
    <div className="banner" role="alert" data-testid="error-banner" data-code={error.code}>
      <div>
        <code>{error.code}</code> — {error.message}
      </div>
      {error.retryable ? (
        <div className="muted">The service says this one is worth retrying.</div>
      ) : null}
    </div>
  )
}

/** An advisory that is not a failure — the amber half of the same idea. */
export function Notice({ children, testId }: { children: React.ReactNode; testId?: string }) {
  return (
    <div className="banner" data-tone="warn" role="note" data-testid={testId}>
      {children}
    </div>
  )
}
