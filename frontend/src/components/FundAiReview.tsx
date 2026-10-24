import { useState } from 'react'
import { getFundAiReview, type FundAiReview as Review } from '../api/listings'
import { errorMessage } from '../lib/format'
import { Button } from './ui'
import PointList from './PointList'

const SECTIONS: { key: keyof Review['sections']; label: string }[] = [
  { key: 'returns', label: 'Returns' },
  { key: 'risk', label: 'Risk' },
  { key: 'portfolio', label: 'Portfolio' },
  { key: 'peers', label: 'Against competitors' },
  { key: 'cost', label: 'Cost' },
]

/** On-demand AI read of the fund from the figures on this page. Runs only
 * when asked (it uses an AI call); the reply is cached on the server. */
export default function FundAiReview({ code }: { code: string }) {
  const [review, setReview] = useState<Review | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadedFor, setLoadedFor] = useState(code)
  if (loadedFor !== code) {
    setLoadedFor(code)
    setReview(null)
    setError(null)
  }

  const run = (refresh = false) => {
    setLoading(true)
    setError(null)
    getFundAiReview(code, refresh)
      .then(setReview)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }

  return (
    <section id="fund-ai" data-section="AI review" className="scroll-mt-6 space-y-4 border-t border-line pt-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            AI fund review
          </h3>
          <p className="text-xs text-muted">
            The AI reads this page's numbers: rolling returns against the benchmark, risk, rank among competitors, holdings and cost.
          </p>
        </div>
        {review ? (
          <Button variant="secondary" size="sm" icon="refresh" loading={loading} onClick={() => run(true)}>
            Refresh
          </Button>
        ) : (
          <Button size="sm" icon="cpu" loading={loading} onClick={() => run()}>
            {loading ? 'Reading the fund…' : 'Run AI review'}
          </Button>
        )}
      </div>

      {error && <p className="text-xs text-down">{error}</p>}
      {loading && !review && <p className="text-xs text-faint">Gathering returns, risk, holdings and competitors, then asking the AI. This can take up to a minute.</p>}

      {review && (
        <div className="space-y-4">
          <p className="text-sm leading-relaxed">{review.summary}</p>
          {(review.strengths.length > 0 || review.concerns.length > 0) && (
            <div className="grid gap-4 sm:grid-cols-2">
              <PointList title="Strengths" tone="text-up" items={review.strengths} />
              <PointList title="Watch out for" tone="text-warn" items={review.concerns} />
            </div>
          )}
          {SECTIONS.some((s) => review.sections[s.key]) && (
            <dl className="divide-y divide-line rounded-lg bg-canvas px-4">
              {SECTIONS.filter((s) => review.sections[s.key]).map((s) => (
                <div key={s.key} className="grid gap-1 py-2.5 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4">
                  <dt className="text-xs font-medium text-muted">{s.label}</dt>
                  <dd className="text-sm">{review.sections[s.key]}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="text-[12px] text-faint">
            AI-generated from past data on {review.generated_at}; it can be wrong.
            {' An explanation of the figures, not a recommendation.'}
          </p>
        </div>
      )}
    </section>
  )
}
