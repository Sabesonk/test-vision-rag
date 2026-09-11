/**
 * The operator's bearer token — typed into the page, held for the tab, sent on every call.
 *
 * **Not built into the bundle.** A `VITE_API_TOKEN` would be substituted at build time and
 * shipped to every browser that loads the app, which is a credential in an image (§15.2). The
 * operator supplies it, and `sessionStorage` is the store because it dies with the tab: a shared
 * workstation should not keep a corpus credential across sessions.
 *
 * This is browser state, not server state — C11 bans a *server-held* session, and it bans it
 * because a stateless service can be replicated. A token in the operator's own tab is the
 * opposite arrangement: every request carries its own identity and any replica can serve it.
 */

const KEY = 'vsir.token'

export function readToken(): string {
  try {
    return window.sessionStorage.getItem(KEY) ?? ''
  } catch {
    // Private-mode Safari throws on `sessionStorage`. An unauthenticated console is a usable
    // console — the operator retypes the token — so this is a degradation, not a failure.
    return ''
  }
}

export function writeToken(token: string): void {
  try {
    if (token) window.sessionStorage.setItem(KEY, token)
    else window.sessionStorage.removeItem(KEY)
  } catch {
    /* see readToken */
  }
}
