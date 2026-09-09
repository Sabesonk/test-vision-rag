"""Tokenisation (Spec §5.6). ``tok()`` mirrors **Qdrant's WORD tokenizer**, not `impl`'s regex.

This module is four lines of logic and one of the easiest ways to make the whole system wrong.

`verify` reasons in Python about what the index matched. If ``tok()`` and Qdrant disagree by one
token, `verify` says *present* where the index found nothing, or *absent* where it found the page —
and the disagreement is invisible, because both halves are individually sensible.

So the porting hazard in §2.4 is load-bearing: `impl`'s ``TOKEN_RE`` was
``[A-Za-z0-9]+(?:[./\\-_][A-Za-z0-9]+)*``, which deliberately keeps ``84-5140.0020`` as **one**
token, and ``token_set()`` additionally joined adjacent tokens. Both existed to make the deleted
curated-keyword gate work. Qdrant's ``WORD`` tokenizer does neither — it yields
``[84, 5140, 0020]`` — which is precisely why ``phrase_matching`` is the mechanism (§5.5).
**Neither behaviour is ported.** An L0 differential test asserts agreement with a live
``qdrant/qdrant:v1.19.0`` on a fixed corpus of labels, so a Qdrant upgrade fails the build rather
than silently changing what `verify` believes.
"""
from __future__ import annotations

import unicodedata

#: Qdrant's WORD tokenizer keeps runs of letters and digits and treats everything else as a
#: separator. `min_token_len=1` on the index (§5.5) is what keeps `SI3`, `84` and `0020`, so
#: nothing here drops a short token either.
MIN_TOKEN_LEN = 1


def _is_token_char(char: str) -> bool:
    """A token character is alphanumeric. Everything else separates.

    Unicode-aware because the corpus is Italian and English: `però` is one token, and a
    byte-oriented `[A-Za-z0-9]+` would split it into two.
    """
    return char.isalnum()


def tok(text: str) -> list[str]:
    """Lowercased tokens, in order, punctuation as a separator, nothing shorter than one character.

    Order is preserved because a phrase match is about order: ``"SF 1.1A"`` is the phrase
    ``[sf, 1, 1a]``, and a set would match a page carrying those tokens anywhere.
    """
    tokens: list[str] = []
    current: list[str] = []
    for char in unicodedata.normalize("NFKC", text):
        if _is_token_char(char):
            current.append(char)
        elif current:
            tokens.append("".join(current).lower())
            current = []
    if current:
        tokens.append("".join(current).lower())
    return [token for token in tokens if len(token) >= MIN_TOKEN_LEN]


def token_set(text: str) -> set[str]:
    """The distinct tokens of ``text``.

    Used where membership is the question — ``codes_in_text`` and ``grounded_rate`` (§5.7) — and
    never for matching, which is always a phrase. **`impl`'s adjacent-token joins are not ported**
    (§2.4): they made ``84 5140`` a token in its own right, which is a match this system must not
    be able to make.
    """
    return set(tok(text))
