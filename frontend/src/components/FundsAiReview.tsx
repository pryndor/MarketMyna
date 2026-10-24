import { useState } from 'react'
import { getFundsAiReview, type FundsAiReview as Review } from '../api/portfolio'
import { errorMessage, num } from '../lib/format'
import { Button, Card, CardBody, CardHeader } from './ui'
import PointList from './PointList'

const SECTIONS: { key: keyof Review['sections']; label: string }[] = [
  { key: 'mix', label: 'Asset mix' },
  { key: 'overlap', label: 'Overlap' },
  { key: 'concentration', label: 'Concentration' },
  { key: 'risk', label: 'Risk' },
]

/** On-demand AI read of the whole fund portfolio: mix, overlap, look-through
 * stocks and sectors, and each fund's role. Runs only when asked. */
export default function FundsAiReview({ portfolio, version }: { portfolio: string; version: string }) {
  const [review, setReview] = useState<Review | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadedFor, setLoadedFor] = useState(`${portfolio}|${version}`)
  if (loadedFor !== `${portfolio}|${version}`) {
    // A trade changes the portfolio: the old review no longer describes it.
    setLoadedFor(`${portfolio}|${version}`)
    setReview(null)
    setError(null)
  }

  const run = (refresh = false) => {
    setLoading(true)
    setError(null)
    getFundsAiReview(portfolio, refresh)
      .then(setReview)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }

  return (
    <Card id="section-fund-ai" section="AI portfolio review">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            AI portfolio review
          </span>
        }
        description="The AI reads your funds' mix, overlap, the stocks and sectors underneath, and each fund's role"
        icon="cpu"
        actions={
          review ? (
            <Button variant="ghost" size="sm" icon="refresh" loading={loading} onClick={() => run(true)}>
              Refresh
            </Button>
          ) : (
            <Button size="sm" icon="cpu" loading={loading} onClick={() => run()}>
              {loading ? 'Reading your funds…' : 'Run AI review'}
            </Button>
          )
        }
      />
      <CardBody className="space-y-5">
        {error && <p className="text-xs text-down">{error}</p>}
        {!review && !error && (
          <p className="text-xs text-muted">
            {loading
              ? 'Reading every fund’s holdings and asking the AI. With many funds this can take a minute or two.'
              : 'Run it for a plain-language read of how your fund portfolio is built.'}
          </p>
        )}

        {review && (
          <>
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
                  <div key={s.key} className="grid gap-1 py-2.5 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-4">
                    <dt className="text-xs font-medium text-muted">{s.label}</dt>
                    <dd className="text-sm">{review.sections[s.key]}</dd>
                  </div>
                ))}
              </dl>
            )}

            {review.look_through?.top_sectors_of_portfolio?.length ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <Chips title="Biggest sectors across your funds" items={review.look_through.top_sectors_of_portfolio} />
                <Chips title="Biggest stocks across your funds" items={review.look_through.top_stocks_of_portfolio ?? []} />
                {review.look_through.covered_pct != null && review.look_through.covered_pct < 95 && (
                  <p className="text-[12px] text-faint sm:col-span-2">
                    Holdings were available for funds making up {num(review.look_through.covered_pct, 0)}% of the portfolio.
                  </p>
                )}
              </div>
            ) : (
              review.look_through?.covered_pct != null && (
                <p className="text-[12px] text-faint">
                  Stocks and sectors across your funds are left out: holdings are known for only {num(review.look_through.covered_pct, 0)}% of the portfolio.
                </p>
              )
            )}

            {review.funds.length > 0 && (
              <div>
                <div className="mb-1.5 text-xs font-semibold text-muted">Each fund's role</div>
                <ul className="divide-y divide-line">
                  {review.funds.map((f) => (
                    <li key={f.code} className="grid gap-1 py-2 sm:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] sm:gap-4">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium" title={f.name ?? f.code}>{f.name ?? f.code}</div>
                        {f.weight_pct != null && <div className="text-xs text-faint">{num(f.weight_pct, 1)}% of the portfolio</div>}
                      </div>
                      <p className="text-sm text-fg/90">{f.note}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-[12px] text-faint">
              AI-generated from past data on {review.generated_at}; it can be wrong.
              {' An explanation of your portfolio, not a recommendation.'}
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}


function Chips({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-muted">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((x) => (
          <span key={x} className="rounded-md bg-canvas px-2 py-1 text-xs text-muted ring-1 ring-line ring-inset">{x}</span>
        ))}
      </div>
    </div>
  )
}
