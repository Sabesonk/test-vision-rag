/**
 * `POST /ask` — the one call this console makes that can spend money, and the only one that
 * returns prose.
 *
 * A **mutation**, not a query, and that is not a technicality. A query is something React Query
 * may repeat: on a window focus, on a reconnect, on a remount. `/ask` runs the loop, and the loop
 * may take the `read` route, which bills a Gemini call and decrements `reads_remaining`. A
 * question must be asked because somebody asked it.
 */
import { useMutation } from '@tanstack/react-query'

import { ApiError, ask } from '../api/client.ts'
import type { AskResponse } from '../api/types.ts'
import type { Scope } from '../api/requests.ts'

export interface AskInput {
  question: string
  scope?: Scope
  exclude?: string[]
}

export function useAsk() {
  return useMutation<AskResponse, ApiError, AskInput>({
    mutationKey: ['ask'],
    mutationFn: (input) =>
      ask({ question: input.question, scope: input.scope ?? {}, exclude: input.exclude ?? [] }),
    retry: false,
  })
}
