import { useEffect, useState } from 'react'
import { getCeoBrief, getLeadership, type CeoBrief, type CeoVerdict, type Leadership } from '../api/stocks'
import { cx } from '../lib/cx'
import { compact, errorMessage } from '../lib/format'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Skeleton } from './ui'

const VERDICT_TONE: Record<CeoVerdict, 'up' | 'accent' | 'warn' | 'down'> = {
  strong: 'up',
  steady: 'accent',
  uncertain: 'warn',
  concerning: 'down',
}

/** ISS scores run 1 (low risk) to 10 (high risk). */
function riskClass(score: number) {
  return score <= 3 ? 'bg-up' : score <= 6 ? 'bg-warn' : 'bg-down'
}

function initials(name: string) {
  const parts = name.replace(/^(mr|mrs|ms|dr|shri|smt)\.?\s+/i, '').split(' ').filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
}

function BulletList({ items, tone }: { items: string[]; tone: 'up' | 'down' }) {
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2 text-sm leading-relaxed text-fg/90">
          <span className={cx('mt-2 h-1.5 w-1.5 shrink-0 rounded-full', tone === 'up' ? 'bg-up' : 'bg-down')} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

/** The chief executive (from filings) plus an optional AI brief: who they
 * are, what they achieved, where they stumbled, and how safe the company
 * looks under them. */
export default function LeadershipCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<Leadership | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [brief, setBrief] = useState<{ data?: CeoBrief; error?: string; loading?: boolean }>({})

  useEffect(() => {
    if (market === 'crypto') return
    let cancelled = false
    setData(null)
    setError(null)
    setBrief({})
    getLeadership(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  const runBrief = () => {
    setBrief({ loading: true })
    getCeoBrief(symbol, market)
      .then((d) => setBrief({ data: d }))
      .catch((err) => setBrief({ error: errorMessage(err) }))
  }

  if (market === 'crypto') return null

  const ceo = data?.ceo
  const b = brief.data

  return (
    <Card id="section-leadership" section="CEO & leadership">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            CEO & leadership {b && <Badge tone={VERDICT_TONE[b.verdict]}>{b.verdict}</Badge>}
          </span>
        }
        description="Who runs the company, their track record, and how safe it looks under them"
      />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-xs text-faint">Not available: {error}</p>
        ) : !data ? (
          <div className="flex items-center gap-4">
            <Skeleton className="h-12 w-12 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-32" />
            </div>
          </div>
        ) : (
          <>
            {ceo && (
              <div className="flex flex-wrap items-center gap-4">
                <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-accent-fg ring-1 ring-accent/30">
                  {initials(ceo.name)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-base font-semibold">{ceo.name}</div>
                  <div className="text-xs text-muted">
                    {[ceo.title, ceo.age && `age ${ceo.age}`].filter(Boolean).join(' · ')}
                  </div>
                </div>
                {ceo.total_pay != null && (
                  <div className="text-end">
                    <div className="text-xs font-medium text-muted">Total pay{ceo.fiscal_year ? ` (FY${ceo.fiscal_year})` : ''}</div>
                    <div className="tabular mt-0.5 text-sm font-semibold">
                      {compact(ceo.total_pay)} {data.currency}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ------------------------------------------ AI brief */}
            {b ? (
              <div className="space-y-4 rounded-lg bg-canvas p-4">
                <div>
                  <div className="mb-1 text-xs font-medium text-accent-fg">Introduction</div>
                  <p className="text-sm leading-relaxed text-fg/90">{b.introduction}</p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {b.achievements.length > 0 && (
                    <div>
                      <div className="mb-1.5 text-xs font-semibold tracking-wide text-up uppercase">Achievements</div>
                      <BulletList items={b.achievements} tone="up" />
                    </div>
                  )}
                  {b.pitfalls.length > 0 && (
                    <div>
                      <div className="mb-1.5 text-xs font-semibold tracking-wide text-down uppercase">Pitfalls</div>
                      <BulletList items={b.pitfalls} tone="down" />
                    </div>
                  )}
                </div>
                {b.verdict_reason && (
                  <div className="border-t border-line pt-3">
                    <div className="mb-1 flex items-center gap-2 text-xs font-medium text-muted">
                      Company under this CEO <Badge tone={VERDICT_TONE[b.verdict]}>{b.verdict}</Badge>
                    </div>
                    <p className="text-sm leading-relaxed text-fg/90">{b.verdict_reason}</p>
                  </div>
                )}
                <p className="text-[12px] text-faint">AI-written from the model's knowledge and recent headlines - verify key facts.</p>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" variant="secondary" icon="cpu" loading={brief.loading} onClick={runBrief} disabled={!ceo}>
                  {brief.loading ? 'Writing CEO brief…' : 'AI CEO brief'}
                </Button>
                <span className="text-[12px] text-faint">Introduction, achievements, pitfalls and a verdict from your configured AI model.</span>
              </div>
            )}
            {brief.error && (
              <Alert title="CEO brief failed" onDismiss={() => setBrief({})}>
                {brief.error}
              </Alert>
            )}

            {/* ------------------------------------------ governance */}
            {data.governance.length > 0 && (
              <div>
                <div className="mb-2 flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-muted">Governance risk (1 low – 10 high)</span>
                  {data.governance_as_of && <span className="text-[12px] text-faint">ISS · {data.governance_as_of}</span>}
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {data.governance.map((g) => (
                    <div key={g.key} className="flex items-center gap-2">
                      <span className="w-28 shrink-0 text-xs text-muted">{g.label}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                        <div className={cx('h-full rounded-full', riskClass(g.score))} style={{ width: `${g.score * 10}%` }} />
                      </div>
                      <span className="tabular w-5 text-end text-xs font-medium">{g.score}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ------------------------------------------ other officers */}
            {data.officers.length > 0 && (
              <div>
                <div className="mb-1.5 text-xs font-medium text-muted">Other key officers</div>
                <dl className="divide-y divide-line">
                  {data.officers.map((o) => (
                    <div key={o.name} className="flex items-baseline justify-between gap-3 py-1.5">
                      <dt className="min-w-0 truncate text-sm">{o.name}</dt>
                      <dd className="min-w-0 max-w-[60%] text-end text-xs text-muted">{o.title}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}
