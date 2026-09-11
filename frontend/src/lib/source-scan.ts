/**
 * A lexical scanner over this app's own source, for the two §16 Frontend rules that no compiler
 * enforces: **no `any`**, and **no raw hex colour in a component**.
 *
 * `tsc --noEmit` with `noImplicitAny` catches an *inferred* `any` and says nothing about a
 * written one; there is no compiler flag that bans the keyword, and ESLint is not a dependency of
 * this project (§4.2 pins the stack, and a lint toolchain for two rules is a poor trade). So the
 * rules are a test, and this module is the part of that test worth testing on its own.
 *
 * **Why a lexical scan and not a parse.** TypeScript 7 is the native compiler: it no longer ships
 * the JavaScript `createSourceFile` API the old scan would have used, and its replacement
 * (`typescript/unstable/ast`) is both unstable and, at 7.0.2, unusable from Node here. What
 * matters for these two rules is not a syntax tree but *which characters are code* — the word
 * "any" appears in the prose of half the files in `lib/`, and `#fff` inside a comment is a note,
 * not a colour. Removing comments and literals is exactly the discrimination the rules need, and
 * it is small enough to be read and tested rather than trusted.
 *
 * The two scans strip different things, on purpose:
 *
 *   * **`any`** is a type keyword, so comments *and* literals go — `'any'` in a string is data.
 *   * **a raw hex** is most often *inside* a string (`style={{ color: '#f00' }}`), which is the
 *     violation itself. Only comments go, so the prose above may discuss `#0e1116` freely while
 *     a component that ships one fails.
 */

/** Replace a run of source with spaces, preserving newlines so line numbers survive. */
function blank(text: string): string {
  return text.replace(/[^\n]/g, ' ')
}

/**
 * Line and block comments → whitespace.
 *
 * String literals are walked over rather than ignored, because `'// not a comment'` is a string
 * and `"/*"` inside one would otherwise swallow the rest of the file.
 */
export function stripComments(source: string): string {
  let out = ''
  let index = 0

  while (index < source.length) {
    const char = source[index]
    const next = source[index + 1]

    if (char === '/' && next === '/') {
      const stop = source.indexOf('\n', index)
      const end = stop === -1 ? source.length : stop
      out += blank(source.slice(index, end))
      index = end
    } else if (char === '/' && next === '*') {
      const stop = source.indexOf('*/', index + 2)
      const end = stop === -1 ? source.length : stop + 2
      out += blank(source.slice(index, end))
      index = end
    } else if (char === '"' || char === "'" || char === '`') {
      const end = endOfString(source, index)
      out += source.slice(index, end)
      index = end
    } else {
      out += char
      index += 1
    }
  }
  return out
}

/** The index one past the string literal starting at `start`. Handles escapes; stops at EOF. */
function endOfString(source: string, start: number): number {
  const quote = source[start]
  let index = start + 1
  while (index < source.length) {
    const char = source[index]
    if (char === '\\') {
      index += 2
      continue
    }
    if (char === quote) return index + 1
    // An unterminated single- or double-quoted string cannot cross a line; a template can.
    if (char === '\n' && quote !== '`') return index
    index += 1
  }
  return source.length
}

/**
 * String, template and regular-expression literals → whitespace. Run **after** `stripComments`.
 *
 * A `/` is a regex only where a value cannot already have appeared, which is decided here by the
 * previous non-space character — the standard heuristic, and sufficient for this codebase: an
 * expression that divides by a parenthesised term is the case it would get wrong, and that case
 * still cannot manufacture the word `any`.
 */
export function stripLiterals(source: string): string {
  let out = ''
  let index = 0
  let previous = ''

  while (index < source.length) {
    const char = source[index]

    if (char === '"' || char === "'" || char === '`') {
      const end = endOfString(source, index)
      out += blank(source.slice(index, end))
      index = end
      previous = char
      continue
    }

    if (char === '/' && regexAllowedAfter(previous)) {
      const end = endOfRegex(source, index)
      if (end > index + 1) {
        out += blank(source.slice(index, end))
        index = end
        previous = '/'
        continue
      }
    }

    out += char
    if (char !== undefined && char.trim() !== '') previous = char
    index += 1
  }
  return out
}

/** After one of these, a `/` opens a regex rather than dividing. */
function regexAllowedAfter(previous: string): boolean {
  return previous === '' || '(,=:[!&|?{};+-*%~^<>'.includes(previous)
}

/** One past the regex literal at `start`, or `start + 1` if it is not one after all. */
function endOfRegex(source: string, start: number): number {
  let index = start + 1
  let inClass = false
  while (index < source.length) {
    const char = source[index]
    if (char === '\\') {
      index += 2
      continue
    }
    if (char === '\n') return start + 1
    if (char === '[') inClass = true
    else if (char === ']') inClass = false
    else if (char === '/' && !inClass) {
      index += 1
      while (index < source.length && /[a-z]/.test(source[index] ?? '')) index += 1
      return index
    }
    index += 1
  }
  return start + 1
}

export interface Hit {
  /** 1-indexed, so a failure message points at something an editor can open. */
  line: number
  text: string
}

function hits(source: string, pattern: RegExp, original: string): Hit[] {
  const found: Hit[] = []
  const lines = source.split('\n')
  const originalLines = original.split('\n')
  lines.forEach((line, index) => {
    if (pattern.test(line)) {
      found.push({ line: index + 1, text: (originalLines[index] ?? line).trim() })
    }
    pattern.lastIndex = 0
  })
  return found
}

/** Every written `any` type keyword in code — comments and literals excluded. */
export function findAny(source: string): Hit[] {
  return hits(stripLiterals(stripComments(source)), /(?<![\w$])any(?![\w$])/, source)
}

/** Every `#rgb` / `#rrggbb` / `#rrggbbaa` outside a comment — a string literal is *in* scope. */
export function findRawHex(source: string): Hit[] {
  return hits(stripComments(source), /#[0-9a-fA-F]{3,8}\b/, source)
}
