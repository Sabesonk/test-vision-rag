/**
 * The three narrowing rungs, as queries — §8.1's *"the same move repeated at three zoom levels"*
 * with a person on the controls instead of the runner.
 *
 * Each rung is a query rather than a mutation because a skim is free, repeatable and read-only:
 * refetching one costs a Qdrant search and changes nothing. `/ask` is the opposite, and is a
 * mutation for exactly that reason (`useAsk.ts`).
 *
 * `enabled` is how a rung stays unasked until it has what it needs. Descending to chapters
 * without a `doc_id` would search the whole corpus and present the result as if it were that
 * document's — the scope is the question, so an incomplete scope is not a smaller question.
 */
import { useQuery } from '@tanstack/react-query'

import { skimDocuments, skimPages, skimSections } from '../api/client.ts'
import type { DocHit, PageHit, SearchResponse, SectionHit } from '../api/types.ts'

const SKIM_QUERY = {
  // A skim is cheap but it is not free, and the ladder revisits a rung every time the operator
  // climbs back up. One minute is long enough to make "up, then down again" instant and short
  // enough that a fresh ingest shows up without a reload.
  staleTime: 60_000,
  retry: false,
} as const

export function useBinders(query: string, enabled: boolean) {
  return useQuery<SearchResponse<DocHit>>({
    queryKey: ['skim_documents', query],
    queryFn: () => skimDocuments({ query }),
    enabled,
    ...SKIM_QUERY,
  })
}

export function useChapters(query: string, docId: string | null) {
  return useQuery<SearchResponse<SectionHit>>({
    queryKey: ['skim_sections', query, docId],
    queryFn: () => skimSections({ query, scope: { doc_id: docId } }),
    enabled: docId !== null,
    ...SKIM_QUERY,
  })
}

export function usePages(query: string, docId: string | null, sectionId: string | null) {
  return useQuery<SearchResponse<PageHit>>({
    queryKey: ['skim_pages', query, docId, sectionId],
    queryFn: () =>
      skimPages({
        query,
        scope: sectionId === null ? { doc_id: docId } : { doc_id: docId, section_id: sectionId },
      }),
    enabled: docId !== null,
    ...SKIM_QUERY,
  })
}
