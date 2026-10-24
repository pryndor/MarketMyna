import { useEffect, useState } from 'react'
import { getCentralBanks, type PolicyRate } from '../api/macro'
import { errorMessage, num, signed } from '../lib/format'

import InsightLoader from './InsightLoader'

const SHORT = 8 // rows before "Show all"

/** 3.625 -> "3.625", 5.5 -> "5.50" */
function rate(v: number | null): string {
  if (v == null) return '—'
  return num(v, Number.isInteger(Math.round(v * 1000) / 10) ? 2 : 3)
}

function lastMove(r: PolicyRate): string {
  if (r.changed_between) return `${r.direction === 'cut' ? 'Cut' : 'Raised'} from ${rate(r.previous)}% after ${r.changed_between[0]}`
  if (!r.last_change || r.previous == null) return 'No change in 2 years'
  return `${r.direction === 'cut' ? 'Cut' : 'Raised'} from ${rate(r.previous)}% on ${r.last_change}`
}

/** Policy rates of about 40 central banks with their last move and real rate. */
export default function CentralBanks() {
  const [rows, setRows] = useState<PolicyRate[] | null>(null)
  const [meta, setMeta] = useState<{ stale: boolean; source: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [all, setAll] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getCentralBanks(controller.signal)
      .then((d) => {
        setRows(d.rows)
        setMeta({ stale: d.stale, source: d.source })
      })
      .catch((err) => !controller.signal.aborted && setError(errorMessage(err)))
    return () => controller.abort()
  }, [])

  const shown = rows ? (all ? rows : rows.slice(0, SHORT)) : []
  const old = (d: string) => Date.now() - new Date(d).getTime() > 60 * 86400000

  return (
    <div>
      <div className="px-5 py-3">
        <h2 className="text-sm font-semibold">Central bank rates</h2>
        <p className="text-xs text-muted">Policy rate, last move, change over a year and the rate after inflation</p>
      </div>
      <div className="space-y-3 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!rows && !error && <InsightLoader className="min-h-40" steps={['Fetching policy rates…']} />}
        {rows && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[600px] text-sm">
                <thead>
                  <tr className="text-start text-xs text-muted">
                    <th className="py-1 pe-3 font-medium">Economy</th>
                    <th className="py-1 pe-3 text-end font-medium">Rate</th>
                    <th className="py-1 pe-3 font-medium">Last move</th>
                    <th className="py-1 pe-3 text-end font-medium">1y change</th>
                    <th className="py-1 text-end font-medium" title="Policy rate minus the IMF's inflation projection for this year">
                      Real rate
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.area} className="border-t border-line">
                      <td className="py-1.5 pe-3" title={r.bank}>
                        {r.name}
                        <div className="text-[11px] text-faint">
                          {r.bank}
                          {old(r.as_of) && ` · data to ${r.as_of}`}
                        </div>
                      </td>
                      <td className="tabular py-1.5 pe-3 text-end font-semibold">{rate(r.rate)}%</td>
                      <td className={`py-1.5 pe-3 text-xs ${r.direction === 'cut' ? 'text-up' : r.direction === 'hike' ? 'text-down' : 'text-muted'}`}>
                        {lastMove(r)}
                      </td>
                      <td className="tabular py-1.5 pe-3 text-end">{r.change_1y == null ? '—' : `${signed(r.change_1y, 2)} pts`}</td>
                      <td className="tabular py-1.5 text-end" title={r.inflation != null ? `IMF inflation ${num(r.inflation, 1)}%` : undefined}>
                        {r.real_rate == null ? '—' : `${signed(r.real_rate, 2)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length > SHORT && (
              <button type="button" className="text-xs text-muted underline hover:text-fg" onClick={() => setAll((a) => !a)}>
                {all ? 'Show fewer' : `Show all ${rows.length}`}
              </button>
            )}
            {meta && (
              <p className="text-[12px] text-faint">
                Source: {meta.source}
                {meta.stale ? ' (saved copy: the BIS did not answer)' : ''}. Cuts are shown green and hikes red as a convention, not a
                judgement.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
