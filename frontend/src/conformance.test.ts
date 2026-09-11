/**
 * The frontend's conformance gate — §16's rules, and §7.1's, over this app's own source.
 *
 * The backend has Spec §12.5's greps in `test-unit.sh`; this is their other half. The rules here
 * are the ones no compiler enforces and no component test would notice, because each is about
 * something that must be true of **every** file rather than of one render:
 *
 *   * **no written `any`.** `tsc --noEmit` with `noImplicitAny` catches an inferred one and says
 *     nothing about a written one, and there is no compiler flag that bans the keyword.
 *   * **no raw hex in a component.** The trust badges are the product, and a badge whose colour
 *     is written inline can be restyled by someone who has not read what it means.
 *   * **no `inline: true`, and no reading of `bytes_b64`.** *"A `bytes_b64` in a skim row is a P2
 *     violation and an asserted test failure"*, and the console is where an accidental
 *     `inline: true` would move megabytes through JSON twice.
 *
 * The scanner is `lib/source-scan.ts`, tested separately — a conformance check that quietly stops
 * finding things is worse than none, because it reports a clean scan over source it failed to
 * read.
 */
import { describe, expect, it } from 'vitest'

import { findAny, findRawHex, stripComments } from './lib/source-scan.ts'

const SOURCES = import.meta.glob('./**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const files = Object.entries(SOURCES)

function report(hits: [string, { line: number; text: string }[]][]): string {
  return hits
    .flatMap(([path, found]) => found.map((hit) => `${path}:${hit.line}  ${hit.text}`))
    .join('\n')
}

describe('the scan reaches the source', () => {
  it('found this app’s modules, so a clean result means something', () => {
    expect(files.length).toBeGreaterThan(15)
    expect(files.some(([path]) => path.endsWith('components/AgentPanel/Draft.tsx'))).toBe(true)
    expect(files.some(([path]) => path.endsWith('api/types.ts'))).toBe(true)
  })
})

describe('§16 Frontend', () => {
  it('has no `any` anywhere in src/', () => {
    const offenders = files
      .map(([path, source]) => [path, findAny(source)] as [string, ReturnType<typeof findAny>])
      .filter(([, found]) => found.length > 0)
    expect(report(offenders)).toBe('')
  })

  it('has no raw hex colour in a component', () => {
    const offenders = files
      .filter(([path]) => path.includes('/components/'))
      .map(([path, source]) => [path, findRawHex(source)] as [string, ReturnType<typeof findRawHex>])
      .filter(([, found]) => found.length > 0)
    expect(report(offenders)).toBe('')
  })

  it('keeps every colour in the one stylesheet that is allowed to name one', () => {
    // Wider than §16, which only names components — a hex in `lib/` would be just as invisible
    // to a reviewer. The scanner's own test is exempt for the same reason Spec §12.5's greps
    // never scan theirs: a test for a hex-finder has to contain hex to find.
    const styled = files
      .filter(([path]) => !path.endsWith('lib/source-scan.test.ts'))
      .filter(([, source]) => findRawHex(source).length > 0)
    expect(styled.map(([path]) => path)).toEqual([])
  })
})

describe('§7.1 / D12 — no pixels in a payload', () => {
  it('never asks for `inline: true`', () => {
    const offenders = files.filter(([, source]) =>
      /inline:\s*true/.test(stripComments(source)),
    )
    expect(offenders.map(([path]) => path)).toEqual([])
  })

  it('never reads `bytes_b64` outside the type that declares `fetch` may carry one', () => {
    const offenders = files
      .filter(([path]) => !path.endsWith('api/types.ts'))
      .filter(([, source]) => /bytes_b64/.test(stripComments(source)))
    expect(offenders.map(([path]) => path)).toEqual([])
  })
})

describe('§7.6 — there is no score', () => {
  it('has no `score` field anywhere in the client’s view of the wire', () => {
    const offenders = files.filter(([, source]) =>
      /\bscore\b\s*[:?]/.test(stripComments(source)),
    )
    expect(offenders.map(([path]) => path)).toEqual([])
  })
})
