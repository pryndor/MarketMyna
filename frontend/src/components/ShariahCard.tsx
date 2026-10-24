import { useEffect, useState } from 'react'
import { getShariah, type ShariahCheck, type ShariahProfile, type ShariahVerdict } from '../api/stocks'
import { cx } from '../lib/cx'
import { errorMessage } from '../lib/format'
import { Badge, Card, CardBody, CardHeader, Skeleton } from './ui'

const VERDICT_TONE: Record<ShariahVerdict, 'up' | 'warn' | 'down' | 'neutral'> = {
  halal: 'up',
  doubtful: 'warn',
  haram: 'down',
  unknown: 'neutral',
}

const CHECK_TONE: Record<ShariahCheck['status'], { bar: string; text: string; label: string }> = {
  pass: { bar: 'bg-up', text: 'text-up', label: 'Pass' },
  borderline: { bar: 'bg-warn', text: 'text-warn', label: 'Fails stricter limit' },
  fail: { bar: 'bg-down', text: 'text-down', label: 'Fail' },
  unknown: { bar: 'bg-faint', text: 'text-faint', label: 'No data' },
}

/** One ratio against its limit: the bar spans 0 to 1.5x the limit so a
 * pass sits left of the tick and a fail runs past it. */
function CheckRow({ check }: { check: ShariahCheck }) {
  const tone = CHECK_TONE[check.status]
  const scale = check.limit * 1.5
  const width = check.value == null ? 0 : Math.min(100, (check.value / scale) * 100)
  const tick = (check.limit / scale) * 100
  const strictTick = check.strict_limit != null ? (check.strict_limit / scale) * 100 : null
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
        <span className="text-fg/90">
          {check.label} <span className="text-xs text-faint">/ {check.basis}</span>
        </span>
        <span className="flex shrink-0 items-baseline gap-2">
          <span className="tabular font-semibold">{check.value == null ? '—' : `${check.value.toFixed(1)}%`}</span>
          <span className={cx('text-xs font-medium', tone.text)}>{tone.label}</span>
        </span>
      </div>
      <div className="relative h-1.5 rounded-full bg-raised">
        <div className={cx('h-full rounded-full', tone.bar)} style={{ width: `${width}%` }} />
        <div className="absolute -top-0.5 h-2.5 w-px bg-fg/60" style={{ left: `${tick}%` }} title={`Limit ${check.limit}%`} />
        {strictTick != null && (
          <div
            className="absolute -top-0.5 h-2.5 w-px bg-fg/30"
            style={{ left: `${strictTick}%` }}
            title={`Stricter limit ${check.strict_limit}%`}
          />
        )}
      </div>
      <div className="mt-1 text-xs text-faint">
        Limit {check.limit}%{check.strict_limit != null && ` (stricter ${check.strict_limit}%)`}
        {check.note && ` · ${check.note}`}
      </div>
    </div>
  )
}

/** Halal screen for one stock: business activity, balance-sheet ratios
 * against S&P / AAOIFI limits, and the dividend purification share. */
export default function ShariahCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<ShariahProfile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (market === 'crypto') return
    let cancelled = false
    setData(null)
    setError(null)
    getShariah(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (market === 'crypto') return null

  return (
    <Card id="section-shariah" section="Ethical screen">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Ethical screen {data && <Badge tone={VERDICT_TONE[data.verdict]}>{data.verdict_label}</Badge>}
          </span>
        }
        description="Ethical check: no interest-based business, no excluded activity, low debt and interest income"
      />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-xs text-faint">Not available: {error}</p>
        ) : !data ? (
          <div className="space-y-3">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-full" />
          </div>
        ) : (
          <>
            <ul className="space-y-1.5">
              {data.reasons.map((r) => (
                <li key={r} className="flex gap-2 text-sm leading-relaxed text-fg/90">
                  <span
                    className={cx(
                      'mt-2 h-1.5 w-1.5 shrink-0 rounded-full',
                      data.verdict === 'halal' ? 'bg-up' : data.verdict === 'haram' ? 'bg-down' : 'bg-warn',
                    )}
                  />
                  <span>{r}</span>
                </li>
              ))}
            </ul>

            <div className="rounded-lg bg-canvas p-4">
              <div className="mb-1 flex items-center gap-2 text-xs font-medium text-muted">
                Business activity <Badge tone={VERDICT_TONE[data.business.status]}>{data.business.status}</Badge>
              </div>
              <p className="text-sm text-fg/90">
                {[data.sector, data.industry].filter(Boolean).join(' · ') || 'Sector not published'}
              </p>
              {data.business.flags.length > 0 && (
                <p className="mt-1 text-xs text-warn">Business description mentions: {data.business.flags.join(', ')}</p>
              )}
            </div>

            {data.checks.length > 0 && (
              <div className="space-y-4">
                {data.checks.map((c) => (
                  <CheckRow key={c.key} check={c} />
                ))}
              </div>
            )}

            {data.purification_pct != null && data.purification_pct > 0 && (
              <div className="rounded-lg border border-line p-3 text-sm">
                <span className="font-medium">Give to charity:</span> about{' '}
                <span className="tabular font-semibold">{data.purification_pct.toFixed(2)}%</span> of any dividend - the share of
                revenue that came from interest.
              </div>
            )}

            <p className="text-[12px] text-faint">
              Screen based on {data.source}
              {data.period && ` statements to ${data.period}`}. Standard index limits, with the stricter 30% shown as a
              second tick. A screening aid, not a final ruling - standards differ at the edges; ask a qualified adviser for a firm answer.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
