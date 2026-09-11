/**
 * The console: a question at the top, the page on the left, the agent on the right.
 *
 * Three pieces of state live here and nowhere else, and each one is here for a reason worth
 * writing down.
 *
 * **The token.** Typed in, kept in `sessionStorage` for the tab (`auth/token.ts`), never built
 * into the bundle. §16 requires that a raster is not served without auth, so an unauthenticated
 * console is a console that renders nothing — and it says so, rather than showing empty panels.
 *
 * **The ladder.** Where the reader is on the zoom ladder, including the crop. Browser state
 * about a view, not server state about a corpus — C11 bans a *server-held* session, and this is
 * the arrangement it bans it in favour of: every request carries its own scope, so any replica
 * can serve the next one.
 *
 * **The last response.** Held from the mutation rather than refetched, because re-asking a
 * question can spend money (`hooks/useAsk.ts`).
 *
 * The question does double duty: it is what `/ask` is asked, and it is what the ladder's skims
 * narrow with. That is not a shortcut — it is the same question at three zoom levels, which is
 * what §8.1 says narrowing is, with a person doing it instead of the runner.
 *
 * The **page rung is addressable** (`#/page/<page_id>`), in both directions: a pasted link opens
 * that page, and opening a page puts it in the address bar. It is a `replaceState`, not a push,
 * because moving down a ladder is not navigation a reader wants to unwind one rung per Back
 * press — and it is the only state here that leaves the tab.
 */
import { useEffect, useMemo, useState } from 'react'

import { Banner } from './components/Banner.tsx'
import { AgentPanel } from './components/AgentPanel/AgentPanel.tsx'
import { Viewer } from './components/Viewer/Viewer.tsx'
import { useAsk } from './hooks/useAsk.ts'
import { type Ladder, TOP, hashForPage, jumpToPage, ladderFromHash } from './lib/ladder.ts'
import { evidencePages } from './lib/strip.ts'
import { readToken, writeToken } from './auth/token.ts'

export function App() {
  const [token, setToken] = useState(readToken)
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState('')
  const [ladder, setLadder] = useState<Ladder>(() => ladderFromHash(window.location.hash) ?? TOP)

  const ask = useAsk()
  const response = ask.data ?? null

  const evidence = useMemo(() => evidencePages(response?.answer ?? null), [response])

  // A pasted link, or the Back button on one. `hashchange` fires for both and for nothing else
  // this app does, because the writer below uses `replaceState` and never dispatches it.
  useEffect(() => {
    function onHashChange() {
      const addressed = ladderFromHash(window.location.hash)
      if (addressed !== null) setLadder(addressed)
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // The other direction. Only the page id is addressed — a binder or a chapter is a search
  // result, and a link to one would promise a list that the next ingest can legitimately change.
  useEffect(() => {
    const wanted = `${window.location.pathname}${window.location.search}${hashForPage(ladder.pageId)}`
    if (`${window.location.pathname}${window.location.search}${window.location.hash}` !== wanted) {
      window.history.replaceState(null, '', wanted)
    }
  }, [ladder.pageId])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = question.trim()
    if (trimmed === '') return
    setAsked(trimmed)
    ask.mutate({ question: trimmed })
  }

  /**
   * A citation click. It goes to `claim.page_id` — the page the gate checked the code against —
   * and it rebuilds the ladder from that id rather than descending to it, because a reader who
   * clicked a code in an answer has not browsed anywhere and the breadcrumbs should not claim
   * they have (`lib/ladder.ts::jumpToPage`).
   */
  function selectPage(pageId: string) {
    setLadder(jumpToPage(pageId))
  }

  /**
   * §8.1a's `fetch` route: the operator read the page on the left and wrote what it says.
   *
   * It goes through the **same** mutation the question box uses, because it is the same surface
   * — `POST /ask` either runs the loop or gates a draft — and because the result belongs in the
   * same panel: a badged answer, or a rejection. `claims` is left empty deliberately; the gate
   * re-derives the claim set from the prose and checks the union, so nothing the operator typed
   * escapes a check by not having been declared (§8.4).
   */
  function readOff(pageId: string, text: string) {
    const trimmed = question.trim()
    if (trimmed === '') return
    setAsked(trimmed)
    ask.mutate({ question: trimmed, draft: { text, claims: [], pages: [pageId] } })
  }

  return (
    <div className="app">
      <header className="header">
        <h1>vsir console</h1>
        <form onSubmit={submit} className="header" style={{ padding: 0, border: 'none', flex: '4 1 520px' }}>
          <input
            className="question"
            placeholder="Ask the corpus a question"
            aria-label="question"
            data-testid="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <button type="submit" data-testid="ask" disabled={ask.isPending || question.trim() === ''}>
            {ask.isPending ? 'asking…' : 'ask'}
          </button>
        </form>
        <input
          type="password"
          placeholder="bearer token"
          aria-label="bearer token"
          data-testid="token"
          value={token}
          onChange={(event) => {
            setToken(event.target.value)
            writeToken(event.target.value)
          }}
        />
      </header>

      {token === '' ? (
        <div style={{ padding: 'var(--gap)' }}>
          <div className="banner" data-tone="warn" role="note" data-testid="no-token">
            Every route on this service is bearer-authenticated, including the page rasters. Paste
            an operator token to load anything.
          </div>
        </div>
      ) : null}

      <div style={{ padding: ask.error !== null ? 'var(--gap)' : 0 }}>
        <Banner error={ask.error} />
      </div>

      <div className="zones">
        <Viewer
          query={asked}
          draftQuestion={question}
          ladder={ladder}
          onLadder={setLadder}
          evidence={evidence}
          onReadOff={readOff}
          pending={ask.isPending}
        />
        <AgentPanel response={response} pending={ask.isPending} onSelectPage={selectPage} />
      </div>
    </div>
  )
}
