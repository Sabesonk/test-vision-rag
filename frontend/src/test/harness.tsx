/**
 * Rendering a component that talks to the service, without a service.
 *
 * A fresh `QueryClient` per test, with retries off: a shared one would carry a previous test's
 * cache into the next, and a retry would turn a deliberate refusal into three seconds of waiting
 * before the same assertion.
 */
import type { ReactElement, ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'

export function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  })
}

export function renderWithQuery(ui: ReactElement) {
  const client = newClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, ...render(ui, { wrapper }) }
}
