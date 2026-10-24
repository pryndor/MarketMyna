import { useEffect, useState } from 'react'
import { getFundStyle, type FundStyle as Data } from '../api/listings'
import { cx } from '../lib/cx'
import { errorMessage, num } from '../lib/format'
import { Icon, Skeleton } from './ui'

const SIZES = ['Large', 'Mid', 'Small'] as const
const STYLES = ['Value', 'Blend', 'Growth'] as const

/** Style box from the holdings, valuation against the market, and SEBI category rule checks. */
export default function FundStyle({ code }: { code: string }) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    setError(null)
    getFundStyle(code, controller.signal)
      .then(setData)
      .catch((err) => !controller.signal.aborted && setError(errorMessage(err)))
    return () => controller.abort()
  }, [code])

  return (
    <section id="fund-style" data-section="Style & drift" className="scroll-mt-6 space-y-4 border-t border-line pt-6">
      <div>
        <h3 className="text-sm font-semibold">Style & drift</h3>
        <p className="text-xs text-muted">What kind of fund it really is, judged by what it holds, and whether it stays inside its category's rules.</p>
      </div>
      {error ? (
        <p className="text-xs text-faint">Unavailable right now: {error}</p>
      ) : !data ? (
        <Skeleton className="h-32 w-full" />
      ) : data.status !== 'ok' ? (
        <p className="text-xs text-faint">{data.note}</p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[auto_minmax(0,1fr)]">
          <div>
            <div className="grid grid-cols-[3rem_repeat(3,3.5rem)] gap-1 text-center text-[11px]">
              <span />
              {STYLES.map((s) => (
                <span key={s} className="text-faint">
                  {s}
                </span>
              ))}
              {SIZES.map((size) => (
                <div key={size} className="contents">
                  <span className="self-center text-end text-faint">{size}</span>
                  {STYLES.map((s) => {
                    // a multi-cap fund spans every size: the whole style column lights up
                    const hit = data.style?.label === s && (data.size === size || data.size === 'Multi')
                    return <span key={s} className={cx('h-10 rounded', hit ? (data.size === 'Multi' ? 'bg-accent/60' : 'bg-accent') : 'bg-raised')} />
                  })}
                </div>
              ))}
            </div>
            <div className="mt-2 text-sm font-semibold">
              {data.size ?? '—'}
              {data.size === 'Multi' ? '-cap ' : ' '}
              {data.style?.label ?? ''}
            </div>
          </div>
          <div className="space-y-3">
            <table className="w-full max-w-md text-sm">
              <thead>
                <tr className="text-xs text-faint">
                  <th className="py-1 text-start font-medium" />
                  <th className="py-1 text-end font-medium">This fund</th>
                  <th className="py-1 text-end font-medium">Top 100 companies</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {(
                  [
                    ['P/E', data.fund?.pe, data.market?.pe, 1],
                    ['Price / book', data.fund?.pb, data.market?.pb, 2],
                    ['Return on equity', data.fund?.roe, data.market?.roe, 1],
                  ] as const
                ).map(([label, f, m, d]) => (
                  <tr key={label} className="border-t border-line">
                    <td className="py-1.5 text-start">{label}</td>
                    <td className="py-1.5 text-end">{num(f, d)}{label === 'Return on equity' && f != null ? '%' : ''}</td>
                    <td className="py-1.5 text-end text-muted">{num(m, d)}{label === 'Return on equity' && m != null ? '%' : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.checks && data.checks.length > 0 && (
              <div>
                <div className="mb-1 text-xs font-medium text-muted">SEBI rules for a {data.category}</div>
                <ul className="space-y-1 text-sm">
                  {data.checks.map((c) => (
                    <li key={c.rule} className={cx('flex items-center gap-2', c.ok ? 'text-up' : 'text-down')}>
                      <Icon name={c.ok ? 'check' : 'alert'} className="h-4 w-4" />
                      {c.rule}
                      {!c.ok && <span className="text-xs text-muted">: drifting outside its category</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-[12px] text-faint">
              {num(data.equity_pct, 0)}% in shares, {data.count} stocks, portfolio of {data.as_of}. {data.note}
            </p>
          </div>
        </div>
      )}
    </section>
  )
}
