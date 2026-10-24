import { Fragment, useEffect, useState } from 'react'
import {
  getDipRules,
  getFundAiReview,
  getPortfolioFunds,
  sendTestDipAlert,
  setDipRules,
  type DipRules,
  type FundAiReview,
  type FundRow,
  type PortfolioFunds,
} from '../api/portfolio'
import { toast } from '../lib/toast'
import { cx } from '../lib/cx'
import { errorMessage, num, pct } from '../lib/format'
import InsightLoader from './InsightLoader'
import { ordinal } from './SipDays'
import { Button, Card, CardBody, CardHeader, Icon } from './ui'

// Mutual fund side of a portfolio: personal XIRR per fund, best SIP day and the
// dip check (src/services/mf_lumpsum.py): neutral "dip check" wording with the
// numbers, never "lumpsum opportunity" (src/core/compliance.py).

const inr = (v: number | null | undefined) =>
  v == null ? '—' : `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

function levelLabel(f: FundRow): { text: string; className: string } | null {
  const l = f.lumpsum
  if (l.status !== 'ok' || !l.level) return null
  return { text: `Dip check: ${l.met} of ${l.total}`, className: 'bg-raised text-fg' }
}

export default function FundPortfolio({ portfolio, version }: { portfolio: string; version: string }) {
  const [data, setData] = useState<PortfolioFunds | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [rules, setRules] = useState<DipRules | null>(null)

  useEffect(() => {
    getDipRules(portfolio).then(setRules, () => setRules(null))
  }, [portfolio])

  async function saveRules(next: { levels: number[]; overrides: Record<string, number[]> }) {
    const before = rules
    if (rules) setRules({ ...rules, ...next }) // optimistic
    try {
      setRules(await setDipRules(portfolio, next))
    } catch (e) {
      setRules(before)
      toast.error(errorMessage(e))
    }
  }

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    getPortfolioFunds(portfolio).then(
      (d) => !cancelled && setData(d),
      (e) => !cancelled && setError(errorMessage(e)),
    )
    return () => {
      cancelled = true
    }
  }, [portfolio, version])

  return (
    <Card id="section-funds" section="Mutual funds">
      <CardHeader
        title="Mutual fund portfolio"
        icon="portfolio"
        description="Returns, best SIP day and a dip check for the funds you hold"
      />
      <CardBody className="space-y-5">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && (
          <InsightLoader
            className="min-h-48"
            steps={['Reading each fund’s full NAV history…', 'Working out your returns (XIRR)…', 'Checking each fund’s dip against its own past…']}
          />
        )}
        {data && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ['Invested', inr(data.total.invested)],
                ['Value now', inr(data.total.value)],
                ['Gain', inr(data.total.gain)],
                ['Your return (XIRR)', data.total.xirr_pct != null ? `${num(data.total.xirr_pct, 1)}% a year` : '—'],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg bg-canvas px-3 py-2">
                  <div className="text-xs text-muted">{label}</div>
                  <div className="tabular text-base font-semibold">{value}</div>
                </div>
              ))}
            </div>

            {rules && <DipAlertSettings portfolio={portfolio} rules={rules} onChange={saveRules} />}

            <div className="overflow-x-auto">
              <table className="tabular w-full min-w-[46rem] text-sm">
                <thead className="text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 text-start font-medium">Fund</th>
                    <th className="px-2 py-2 text-end font-medium">Value</th>
                    <th className="px-2 py-2 text-end font-medium">Gain</th>
                    <th className="px-2 py-2 text-end font-medium">XIRR</th>
                    <th className="px-2 py-2 text-end font-medium" title="How far the NAV is below its highest NAV">Below high</th>
                    <th className="px-2 py-2 text-start font-medium">Dip check</th>
                    <th className="px-2 py-2 text-end font-medium" title="Historically best SIP day">SIP day</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.funds.map((f) => {
                    const badge = levelLabel(f)
                    const expanded = open === f.code
                    return (
                      <Fragment key={f.code}>
                        <tr
                          className={cx('cursor-pointer hover:bg-raised', expanded && 'bg-raised')}
                          onClick={() => setOpen(expanded ? null : f.code)}
                        >
                          <td className="max-w-[18rem] py-2 pe-2">
                            <div className="flex items-center gap-1.5">
                              <Icon name="chevron" className={cx('h-3.5 w-3.5 shrink-0 text-faint transition-transform', expanded && 'rotate-90')} />
                              <span className="truncate font-medium" title={f.name}>{f.name}</span>
                            </div>
                            <div className="truncate ps-5 text-xs text-faint">{f.category}</div>
                          </td>
                          <td className="px-2 py-2 text-end">{inr(f.value)}</td>
                          <td className={cx('px-2 py-2 text-end', f.gain >= 0 ? 'text-up' : 'text-down')}>{pct(f.gain_pct, 1)}</td>
                          <td className="px-2 py-2 text-end">{f.xirr_pct != null ? `${num(f.xirr_pct, 1)}%` : '—'}</td>
                          <td className="px-2 py-2 text-end">
                            {f.lumpsum.below_high != null ? `${num(-f.lumpsum.below_high * 100, 1)}%` : '—'}
                          </td>
                          <td className="px-2 py-2">
                            {badge ? (
                              <span className={cx('whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium', badge.className)}>{badge.text}</span>
                            ) : (
                              <span className="text-xs text-faint">{f.asset_class === 'Debt' ? 'Debt fund' : '—'}</span>
                            )}
                          </td>
                          <td className="px-2 py-2 text-end">{f.best_sip_day ? ordinal(f.best_sip_day) : '—'}</td>
                        </tr>
                        {expanded && (
                          <tr>
                            <td colSpan={7} className="bg-canvas px-4 py-3">
                              <FundDetail f={f} portfolio={portfolio} rules={rules} onRules={saveRules} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-[12px] text-faint">
              Click a fund for the details. Each condition compares today with the fund’s own last 10 years of NAVs, not a
              fixed rule. XIRR uses your recorded buys and sells.{' '}
              Facts about past behaviour, not investment advice.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}

function FundDetail({
  f,
  portfolio,
  rules,
  onRules,
}: {
  f: FundRow
  portfolio: string
  rules: DipRules | null
  onRules: (next: { levels: number[]; overrides: Record<string, number[]> }) => void
}) {
  const l = f.lumpsum
  const [review, setReview] = useState<FundAiReview | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function runReview() {
    setBusy(true)
    setReviewError(null)
    try {
      setReview(await getFundAiReview(portfolio, f.code))
    } catch (e) {
      setReviewError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  if (l.status !== 'ok') return <p className="text-sm text-muted">{l.reason}</p>
  return (
    <div className="space-y-3 text-sm">
      <ul className="space-y-1.5">
        {l.conditions?.map((c) => (
          <li key={c.key} className="flex gap-2">
            <span className={cx('font-semibold', c.pass ? 'text-up' : 'text-faint')}>{c.pass ? '✓' : '✗'}</span>
            <span>
              <span className="font-medium">{c.label}</span> <span className="text-muted">— {c.detail}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
        {l.turning != null && <span>{l.turning ? '↗ NAV has started rising again (last 10 days)' : 'No upturn yet in the last 10 days'}</span>}
        {l.recovery_days != null && <span>Past dips this deep took about {Math.round(l.recovery_days / 21)} months to get back to the high</span>}
        {l.rsi != null && <span>RSI {num(l.rsi, 0)}</span>}
        <span>NAV as of {l.as_of}</span>
      </div>
      {rules && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3 text-xs">
          <span className="text-muted">
            % alerts for this fund
            {l.below_52w_high != null && ` (now ${num(-l.below_52w_high * 100, 1)}% below its 52-week high)`}:
          </span>
          <LevelChips
            choices={rules.choices}
            selected={rules.overrides[f.code] ?? rules.levels}
            onChange={(levels) => onRules({ levels: rules.levels, overrides: { ...rules.overrides, [f.code]: levels } })}
          />
          {f.code in rules.overrides ? (
            <button
              type="button"
              className="text-muted underline hover:text-fg"
              onClick={() => {
                const { [f.code]: _drop, ...rest } = rules.overrides
                onRules({ levels: rules.levels, overrides: rest })
              }}
            >
              Use portfolio setting
            </button>
          ) : (
            <span className="text-faint">same as the portfolio</span>
          )}
        </div>
      )}
      <div className="border-t border-line pt-3">
        {!review && (
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" variant="secondary" icon="cpu" loading={busy} onClick={runReview}>
              AI review
            </Button>
            <span className="text-xs text-faint">
              Asks your AI model to explain this dip in plain words.
            </span>
          </div>
        )}
        {reviewError && <p className="mt-2 text-xs text-down">{reviewError}</p>}
        {review && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              AI review
            </div>
            <p className="text-sm">{review.summary}</p>
            {review.reasons.length > 0 && (
              <ul className="list-disc space-y-0.5 ps-5 text-xs text-muted">
                {review.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
            {review.risk && <p className="text-xs text-warn">Risk: {review.risk}</p>}
          </div>
        )}
      </div>
    </div>
  )
}


function LevelChips({ choices, selected, onChange }: { choices: number[]; selected: number[]; onChange: (next: number[]) => void }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {choices.map((c) => {
        const on = selected.includes(c)
        return (
          <button
            key={c}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? selected.filter((x) => x !== c) : [...selected, c].sort((a, b) => a - b))}
            className={cx(
              'rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors',
              on ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:border-line-strong hover:text-fg',
            )}
          >
            {c}%
          </button>
        )
      })}
    </span>
  )
}

/** The user's own % dip alerts for the portfolio: a ladder of levels below the 52-week high. */
function DipAlertSettings({
  portfolio,
  rules,
  onChange,
}: {
  portfolio: string
  rules: DipRules
  onChange: (next: { levels: number[]; overrides: Record<string, number[]> }) => void
}) {
  const [testing, setTesting] = useState(false)
  async function test() {
    setTesting(true)
    try {
      const out = await sendTestDipAlert(portfolio)
      toast.success(`Test alert sent for ${out.fund}`)
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setTesting(false)
    }
  }
  const overrides = Object.keys(rules.overrides).length
  return (
    <div className="rounded-lg border border-line px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium">Dip alerts</div>
          <p className="text-xs text-muted">
            Alert me when a fund falls this far below its 52-week high. Pick one or more; each level alerts once per dip and
            re-arms when the fund gets back near its high.
          </p>
        </div>
        <Button size="sm" variant="secondary" icon="send" loading={testing} onClick={test}>
          Send test alert
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <LevelChips choices={rules.choices} selected={rules.levels} onChange={(levels) => onChange({ levels, overrides: rules.overrides })} />
        <span className="text-xs text-faint">
          {rules.levels.length ? 'for every fund in this portfolio' : 'off'}
          {overrides > 0 && ` · ${overrides} fund${overrides > 1 ? 's' : ''} set separately`}
        </span>
      </div>
    </div>
  )
}
