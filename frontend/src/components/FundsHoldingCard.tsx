import { useEffect, useState } from 'react'
import { getFundsHolding, type FundsHolding } from '../api/listings'
import { cx } from '../lib/cx'
import { num } from '../lib/format'
import { Card, CardBody, CardHeader, Skeleton } from './ui'

const SHOW = 10

/** Mutual fund schemes holding an Indian stock, from the loaded monthly
 * portfolio files. Renders nothing outside India or when no file has it. */
export default function FundsHoldingCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<FundsHolding | null>(null)
  const [failed, setFailed] = useState(false)
  const [all, setAll] = useState(false)

  useEffect(() => {
    if (market !== 'india') return
    const controller = new AbortController()
    setData(null)
    setFailed(false)
    setAll(false)
    getFundsHolding(symbol, controller.signal)
      .then(setData)
      .catch(() => !controller.signal.aborted && setFailed(true))
    return () => controller.abort()
  }, [symbol, market])

  if (market !== 'india' || failed) return null
  if (!data) return <Skeleton className="h-32 w-full" />
  if (!data.funds.length) return null

  const total = data.funds.reduce((s, f) => s + (f.value_cr ?? 0), 0)
  const list = all ? data.funds : data.funds.slice(0, SHOW)
  return (
    <Card help="Mutual funds holding this">
      <CardHeader
        title="Mutual funds holding this"
        icon="portfolio"
        description={`${data.count} scheme${data.count === 1 ? '' : 's'} across ${data.houses_loaded} fund house${data.houses_loaded === 1 ? '' : 's'} loaded · ₹${num(total, 0)} Cr in all`}
      />
      <CardBody className="pt-0">
        <table className="w-full table-fixed text-sm">
          <colgroup>
            <col />
            <col className="w-24" />
            <col className="w-20" />
            <col className="w-20" />
          </colgroup>
          <thead className="text-xs text-muted">
            <tr>
              <th className="py-1 text-start font-medium">Scheme</th>
              <th className="py-1 text-end font-medium">Value</th>
              <th className="py-1 text-end font-medium">% of fund</th>
              <th className="py-1 text-end font-medium">Last month</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {list.map((f) => {
              const delta = f.prev_weight == null ? null : f.weight - f.prev_weight
              return (
                <tr key={`${f.amc}-${f.scheme}`}>
                  <td className="truncate py-1.5 pe-2" title={`${f.scheme} · ${f.amc}`}>
                    {f.scheme}
                    <span className="ms-1 text-xs text-faint">{f.amc.replace(/ Mutual Fund$/, '')}</span>
                  </td>
                  <td className="tabular py-1.5 text-end">{f.value_cr != null ? `₹${num(f.value_cr, 0)} Cr` : '—'}</td>
                  <td className="tabular py-1.5 text-end">{num(f.weight, 2)}%</td>
                  <td className={cx('tabular py-1.5 text-end text-xs', delta == null ? 'text-up' : delta > 0.01 ? 'text-up' : delta < -0.01 ? 'text-down' : 'text-muted')}>
                    {delta == null ? 'New' : `${delta >= 0 ? '+' : ''}${num(delta, 2)}`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {data.funds.length > SHOW && (
          <button type="button" onClick={() => setAll((v) => !v)} className="mt-2 text-xs text-accent-fg hover:underline">
            {all ? 'Show fewer' : `Show all ${data.funds.length}`}
          </button>
        )}
        <p className="mt-2 text-xs text-faint">From fund houses' official monthly portfolio files; only houses loaded so far are counted.</p>
      </CardBody>
    </Card>
  )
}
