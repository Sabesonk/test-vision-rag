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
 */
import { useMemo, useState } from 'react'

import { Banner } from './components/Banner.tsx'
import { AgentPanel } from './components/AgentPanel/AgentPanel.tsx'
import { Viewer } from './components/Viewer/Viewer.tsx'
import { useAsk } from './hooks/useAsk.ts'
import { type Ladder, TOP, jumpToPage } from './lib/ladder.ts'
import { evidencePages } from './lib/strip.ts'
import { readToken, writeToken } from './auth/token.ts'

export function App() {
  const [token, setToken] = useState(readToken)
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState('')
  const [ladder, setLadder] = useState<Ladder>(TOP)

  const ask = useAsk()
  const response = ask.data ?? null

  const evidence = useMemo(() => evidencePages(response?.answer ?? null), [response])

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
        <Viewer query={asked} ladder={ladder} onLadder={setLadder} evidence={evidence} />
        <AgentPanel response={response} pending={ask.isPending} onSelectPage={selectPage} />
      </div>
    </div>
  )
}
