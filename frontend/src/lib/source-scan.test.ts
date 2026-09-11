/**
 * The scanner the conformance test leans on.
 *
 * Worth testing on its own, because a conformance check that silently stops finding things is
 * worse than no check: it reports a clean scan over source it failed to read. Both directions
 * are asserted — the prose in this codebase must not trip it, and real code must.
 */
import { describe, expect, it } from 'vitest'

import { findAny, findRawHex, stripComments, stripLiterals } from './source-scan.ts'

describe('stripComments', () => {
  it('removes line and block comments, keeping line numbers', () => {
    const source = 'const a = 1 // note\n/* two\n   lines */\nconst b = 2'
    const stripped = stripComments(source)
    expect(stripped.split('\n')).toHaveLength(4)
    expect(stripped).toContain('const a = 1')
    expect(stripped).not.toContain('note')
    expect(stripped).not.toContain('lines')
  })

  it('does not treat a `//` inside a string as a comment', () => {
    expect(stripComments("const url = '/pages/x' // real\nconst y = 2")).toContain("'/pages/x'")
    expect(stripComments("const url = 'http://host/a'\nconst y = 2")).toContain('http://host/a')
  })

  it('survives an unterminated block comment rather than looping', () => {
    expect(stripComments('const a = 1\n/* never closed')).toContain('const a = 1')
  })
})

describe('stripLiterals', () => {
  it('blanks strings and templates', () => {
    expect(stripLiterals("const a = 'any'")).not.toContain('any')
    expect(stripLiterals('const a = `any`')).not.toContain('any')
  })

  it('blanks a regular expression literal', () => {
    expect(stripLiterals('const re = /any/g')).not.toContain('any')
    expect(stripLiterals('const re = /[A-Z]{1,3}[0-9]{2,4}/g')).not.toContain('A-Z')
  })

  it('does not mistake division for a regex', () => {
    expect(stripLiterals('const ratio = width / height')).toContain('height')
  })
})

describe('findAny', () => {
  it('finds a written `any` in each position that matters', () => {
    expect(findAny('let x: any')).toHaveLength(1)
    expect(findAny('const f = (x) => x as any')).toHaveLength(1)
    expect(findAny('type T = any[]')).toHaveLength(1)
    expect(findAny('function f(): Record<string, any> {}')).toHaveLength(1)
  })

  it('ignores the word in prose and in data — this codebase is full of both', () => {
    expect(findAny('// no `any` in new code')).toEqual([])
    expect(findAny('/** any of the three badges */')).toEqual([])
    expect(findAny("const label = 'any'")).toEqual([])
  })

  it('ignores an identifier that merely contains it', () => {
    expect(findAny('const anyway = 1; company.anything()')).toEqual([])
  })

  it('reports a 1-indexed line an editor can open', () => {
    expect(findAny('const a = 1\nlet b: any')[0]?.line).toBe(2)
  })
})

describe('findRawHex', () => {
  it('finds a hex colour in a string, which is where a component would hide one', () => {
    expect(findRawHex("style={{ color: '#f00' }}")).toHaveLength(1)
    expect(findRawHex('background: #0e1116;')).toHaveLength(1)
  })

  it('ignores one written in a comment — this file discusses them', () => {
    expect(findRawHex('// the wash is #10281a')).toEqual([])
  })

  it('ignores a fragment identifier that is not a colour', () => {
    expect(findRawHex("const id = 'd@1#p001'")).toEqual([])
  })
})
