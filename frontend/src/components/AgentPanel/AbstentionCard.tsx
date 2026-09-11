/**
 * The honest nothing — §8.5's abstention, with the numbers that make it honest.
 *
 * An abstention is not an error and is not an empty result, and this card has to read that way.
 * What makes it trustworthy rather than a shrug is the coverage: how much was searched, how much
 * of it had no text layer, and **how many image-only pages nobody looked at**. That last number
 * is the one §8.5 is built around — while it is above zero the system may not say *"not in these
 * documents"*, because nobody has been to the pages where it would be.
 *
 * So `image_only_unexamined` is rendered as the headline of a warning rather than a row in a
 * table, and the documents those pages are in are named. A reader who wants the answer knows
 * exactly where to send the next `read`.
 */
import type { Abstention } from '../../api/types.ts'
import { Notice } from '../Banner.tsx'

export function AbstentionCard({ abstention }: { abstention: Abstention }) {
  const blind = abstention.image_only_unexamined

  return (
    <section className="panel" data-testid="abstention" data-reason={abstention.reason}>
      <h2 className="panel-head">
        no answer
        <span className="faint">{abstention.reason}</span>
      </h2>
      <div className="panel-body">
        <p className="draft-text" data-testid="abstention-text">
          {abstention.text}
        </p>

        {blind > 0 ? (
          <Notice testId="blind-spot">
            <b>{blind}</b> image-only page(s) were never examined
            {abstention.blind_documents.length > 0 ? (
              <>
                {' '}
                — in <span className="mono">{abstention.blind_documents.join(', ')}</span>
              </>
            ) : null}
            . Until they are read, this is “not found in the text that was searched”, not “not in
            these documents”.
          </Notice>
        ) : null}

        <div className="numbers" data-testid="coverage">
          <span>
            pages searched <b>{abstention.pages_searched}</b>
          </span>
          <span>
            without a text layer <b>{abstention.pages_no_text}</b>
          </span>
          <span>
            of those, read <b>{abstention.pages_no_text_read}</b>
          </span>
          <span data-testid="image-only-unexamined">
            unexamined <b>{blind}</b>
          </span>
          {abstention.rejected_claims > 0 ? (
            <span data-testid="rejected-claims">
              claims rejected <b>{abstention.rejected_claims}</b>
            </span>
          ) : null}
        </div>

        <p className="card-meta">
          searched: <span className="mono">{abstention.searched.join(', ') || 'nothing'}</span>
        </p>
      </div>
    </section>
  )
}
