import { useEffect, useState } from 'react'
import { getChecklists, type Checklists } from '../api/stocks'
import { cx } from '../lib/cx'
import { errorMessage } from '../lib/format'
import { Card, CardBody, CardHeader, Skeleton } from './ui'

// Published rules of well-known investing styles applied to the filings. Each
// rule shows its number; the card never says what an investor "would buy"
// (docs/future/sebi-compliance-mode.md).

function share(passed: number, tested: number): string {
  if (!tested) return 'bg-line-strong'
  const r = passed / tested
  return r >= 0.75 ? 'bg-up' : r >= 0.4 ? 'bg-warn' : 'bg-down'
}

/** Graham, Buffett-style, Lynch, Greenblatt and Marks-style checklists. */
export default function ChecklistsCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Checklists | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    getChecklists(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (market === 'crypto') return null

  return (
    <Card id="section-checklists" section="Investor checklists">
      <CardHeader title="Investor checklists" description="Published rules of five investing styles, applied to this company's filings" />
      <CardBody className="space-y-4">
        {error ? (
          <p className="text-xs text-faint">Not available: {error}</p>
        ) : !data ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            <div className="grid gap-3 lg:grid-cols-2">
              {data.lenses.map((l) => (
                <div key={l.key} className="min-w-0 rounded-lg border border-line px-3 py-2.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
                    <span className="text-sm font-medium">{l.name}</span>
                    <span className="tabular whitespace-nowrap text-xs text-muted">
                      <span className="font-semibold text-fg">{l.passed}</span> of {l.tested} passed
                      {l.tested < l.total && <span className="text-faint"> · {l.total - l.tested} not testable</span>}
                    </span>
                  </div>
                  <div className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-line" aria-hidden="true">
                    <div className={cx('h-full', share(l.passed, l.tested))} style={{ width: `${l.tested ? (l.passed / l.tested) * 100 : 0}%` }} />
                  </div>
                  <ul className="mt-2 space-y-1 text-[12px]">
                    {l.rules.map((r) => (
                      <li key={r.key} className="flex items-start gap-1.5" title={r.why}>
                        <span className={cx('mt-px w-3 shrink-0 font-semibold', r.pass === true ? 'text-up' : r.pass === false ? 'text-down' : 'text-faint')}>
                          {r.pass === true ? '✓' : r.pass === false ? '✗' : '–'}
                        </span>
                        <span className="min-w-0 flex-1 text-muted">{r.label}</span>
                        <span className="tabular shrink-0 text-end text-faint">{r.value}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[11px] text-faint">
                    {l.source}
                    {l.note && ` · ${l.note}`}
                  </p>
                </div>
              ))}
            </div>
            <p className="text-[12px] text-faint">
              Each rule is a published criterion with the threshold its author gave, checked against {data.source}. – means the figure is
              missing or the rule does not apply ({data.financial_sector ? 'banks and insurers skip balance-sheet tests' : 'e.g. no inventory'}). Hover a
              rule for its reason. These are checklists, not what any of these investors would do, and not advice.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
