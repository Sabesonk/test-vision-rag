/**
 * The client's three promises, asserted rather than documented.
 *
 * Each of these is a network-log acceptance criterion from M7, checked here at L0 so the
 * Playwright suite is confirming a property that is already true rather than discovering it:
 *
 *   * every request carries the bearer token — including a raster, which is why an `<img src>`
 *     cannot be used directly (§16 Security);
 *   * `fetch` is always `inline: false`, set in one place so no component can undo it (P2, D12);
 *   * a non-2xx becomes a typed `ApiError`, never an empty result (§7.1, §11.3).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, fetchPages, lookup, rasterBlob, skimDocuments, verify } from './client.ts'
import { writeToken } from '../auth/token.ts'

interface Call {
  url: string
  init: RequestInit
}

let calls: Call[] = []

function respond(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'test',
    json: async () => body,
    blob: async () => new Blob(['png']),
  } as unknown as Response
}

function stub(response: Response) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit = {}) => {
      calls.push({ url, init })
      return Promise.resolve(response)
    }),
  )
}

function sentBody(index = 0): Record<string, unknown> {
  return JSON.parse(String(calls[index]?.init.body)) as Record<string, unknown>
}

function header(name: string, index = 0): string | undefined {
  return (calls[index]?.init.headers as Record<string, string> | undefined)?.[name]
}

beforeEach(() => {
  calls = []
  writeToken('operator-token')
})

afterEach(() => {
  vi.unstubAllGlobals()
  writeToken('')
})

describe('authentication', () => {
  it('sends the bearer token on a tool call', async () => {
    stub(respond({ status: 'ok', hits: [] }))
    await skimDocuments({ query: 'fuse' })
    expect(header('authorization')).toBe('Bearer operator-token')
  })

  it('sends it on a raster too — the reason an `<img src>` will not do', async () => {
    stub(respond({}))
    await rasterBlob('/pages/d@1%23p001/image?dpi=150')
    expect(calls[0]?.url).toBe('/pages/d@1%23p001/image?dpi=150')
    expect(header('authorization')).toBe('Bearer operator-token')
  })

  it('never puts the token in the URL, where a log or a referrer would keep it', async () => {
    stub(respond({}))
    await rasterBlob('/pages/d@1%23p001/image?dpi=150')
    expect(calls[0]?.url).not.toContain('operator-token')
  })

  it('omits the header entirely when there is no token, rather than sending `Bearer `', async () => {
    writeToken('')
    stub(respond({ status: 'ok', hits: [] }))
    await skimDocuments({ query: 'fuse' })
    expect(header('authorization')).toBeUndefined()
  })
})

describe('fetch is always by reference', () => {
  it('pins `inline: false`', async () => {
    stub(respond({ status: 'ok', result: { pages: [] } }))
    await fetchPages(['d@1#p001'])
    expect(sentBody().inline).toBe(false)
  })

  it('pins it even when a caller passes other options', async () => {
    stub(respond({ status: 'ok', result: { pages: [] } }))
    await fetchPages(['d@1#p001'], { dpi: 300, region: [0, 0, 1, 0.5], include: ['image'] })
    const body = sentBody()
    expect(body.inline).toBe(false)
    expect(body.dpi).toBe(300)
    expect(body.region).toEqual([0, 0, 1, 0.5])
  })

  it('defaults to the dpi the index was built at', async () => {
    stub(respond({ status: 'ok', result: { pages: [] } }))
    await fetchPages(['d@1#p001'])
    expect(sentBody().dpi).toBe(150)
  })
})

describe('the named routes (U031)', () => {
  it('posts each tool to its own path', async () => {
    stub(respond({ status: 'ok', hits: [] }))
    await skimDocuments({ query: 'x' })
    await lookup({ label: 'K158' })
    await verify({ claims: ['K158'], page_ids: ['d@1#p001'] })
    expect(calls.map((call) => call.url)).toEqual([
      '/tools/skim_documents',
      '/tools/lookup',
      '/tools/verify',
    ])
  })

  it('sends `include_unverified: false` unless a caller opts in (D3)', async () => {
    stub(respond({ status: 'ok', hits: [] }))
    await lookup({ label: 'K158' })
    expect(sentBody().include_unverified).toBe(false)
  })
})

describe('a refusal is a refusal', () => {
  it('turns a typed 400 into an ApiError carrying the service’s own code', async () => {
    stub(respond({ error: 'dpi_requires_region', detail: 'pass a region', requested: 400 }, 400))
    await expect(fetchPages(['d@1#p001'], { dpi: 400 })).rejects.toBeInstanceOf(ApiError)
    try {
      await fetchPages(['d@1#p001'], { dpi: 400 })
    } catch (error) {
      const api = error as ApiError
      expect(api.code).toBe('dpi_requires_region')
      expect(api.status).toBe(400)
      expect(api.body.requested).toBe(400)
      expect(api.retryable).toBe(false)
    }
  })

  it('carries `retryable` off an outage body (§11.3)', async () => {
    stub(respond({ error: 'qdrant_unavailable', detail: 'down', retryable: true }, 503))
    try {
      await skimDocuments({ query: 'x' })
      expect.unreachable('a 503 must not resolve')
    } catch (error) {
      expect((error as ApiError).retryable).toBe(true)
    }
  })

  it('still refuses when the body is not JSON — a gateway talking, not this service', async () => {
    const broken = {
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      json: async () => {
        throw new Error('not json')
      },
    } as unknown as Response
    stub(broken)
    try {
      await skimDocuments({ query: 'x' })
      expect.unreachable('a 502 must not resolve')
    } catch (error) {
      const api = error as ApiError
      expect(api.status).toBe(502)
      expect(api.code).toBe('http_502')
    }
  })
})
