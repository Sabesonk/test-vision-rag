/**
 * The root. A `QueryClient`, the app, and nothing else.
 *
 * The defaults matter more than the mounting does. Every one of them turns off a repeat: a
 * console that refetched on window focus would re-run a skim every time the operator came back
 * from the Qdrant dashboard, and a retry on a typed refusal would ask a service that already
 * said `dpi_requires_region` the same unanswerable question three times. §11.3's refusals are
 * decisions, not flakiness — the one thing the client must not do with them is try again.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { App } from './App.tsx'
import './styles.css'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
    mutations: { retry: false },
  },
})

const root = document.getElementById('root')
if (root === null) throw new Error('#root is missing from index.html')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
