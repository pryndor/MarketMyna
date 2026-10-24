import { useEffect, useState } from 'react'
import { getCountryMacro, type CountryMacro as Data } from '../api/macro'
import { errorMessage, num } from '../lib/format'

import InsightLoader from './InsightLoader'

const KEY = 'marketmyna.countries'
const DEFAULT = ['IND', 'USA', 'CHN', 'JPN', 'DEU', 'GBR', 'FRA', 'KOR', 'IDN', 'BRA', 'SAU', 'ARE', 'AUS', 'CAN']

function readCodes(): string[] {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    return Array.isArray(saved) && saved.length ? saved.slice(0, 30) : DEFAULT
  } catch {
    return DEFAULT
  }
}

function value(v: unknown, unit: string): string {
  if (typeof v !== 'number') return '—'
  if (unit === 'US$ bn') return v >= 1000 ? `${num(v / 1000, 2)} tn` : `${num(v, 0)} bn`
  if (unit === 'US$') return num(v, 0)
  return num(v, 1)
}

/** IMF World Economic Outlook figures for a list of countries the viewer picks. */
export default function CountryMacro() {
  const [codes, setCodes] = useState<string[]>(readCodes)
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [yearIdx, setYearIdx] = useState(1)

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(codes))
    } catch {
      /* private mode */
    }
    const controller = new AbortController()
    setError(null)
    getCountryMacro(codes, controller.signal)
      .then(setData)
      .catch((err) => !controller.signal.aborted && setError(errorMessage(err)))
    return () => controller.abort()
  }, [codes])

  const year = data?.years[yearIdx]
  const projected = data && year != null && year >= data.projection_from

  return (
    <div>
      <div className="px-5 py-3">
        <h2 className="text-sm font-semibold">Countries</h2>
        <p className="text-xs text-muted">Growth, inflation, debt and deficits from the IMF, for any country</p>
      </div>
      <div className="space-y-3 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={['Fetching IMF outlook…', 'Lining up countries…']} />}
        {data && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex overflow-hidden rounded-lg border border-line text-xs">
                {data.years.map((y, i) => (
                  <button
                    key={y}
                    type="button"
                    onClick={() => setYearIdx(i)}
                    className={`px-3 py-1.5 ${i === yearIdx ? 'bg-accent-soft font-medium text-fg' : 'text-muted hover:text-fg'}`}
                  >
                    {y}
                    {y >= data.projection_from ? ' projected' : ''}
                  </button>
                ))}
              </div>
              <select
                aria-label="Add a country"
                className="min-w-0 max-w-full rounded-lg border border-line bg-canvas px-2 py-1.5 text-xs"
                value=""
                onChange={(e) => e.target.value && setCodes((c) => [...c.filter((x) => x !== e.target.value), e.target.value].slice(0, 30))}
              >
                <option value="">Add a country…</option>
                {data.countries
                  .filter((c) => !codes.includes(c.code))
                  .map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
              </select>
              {codes.join() !== DEFAULT.join() && (
                <button type="button" className="text-xs text-muted underline hover:text-fg" onClick={() => setCodes(DEFAULT)}>
                  Reset list
                </button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="text-start text-xs text-muted">
                    <th className="py-1 pe-3 font-medium">Country</th>
                    {data.indicators.map((ind) => (
                      <th key={ind.key} className="py-1 pe-3 text-end font-medium" title={ind.note}>
                        {ind.label}
                        <div className="text-[10px] font-normal text-faint">{ind.unit}</div>
                      </th>
                    ))}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.code} className="border-t border-line">
                      <td className="py-1.5 pe-3" title={r.fiscal_year ?? undefined}>
                        {r.name}
                        {r.fiscal_year && <span className="text-faint">*</span>}
                      </td>
                      {data.indicators.map((ind) => {
                        const vals = r[ind.key] as Array<number | null>
                        const v = vals?.[yearIdx]
                        const signedRed = ['NGDP_RPCH', 'GGXCNL_NGDP', 'BCA_NGDPD'].includes(ind.key) && typeof v === 'number' && v < 0
                        return (
                          <td
                            key={ind.key}
                            className={`tabular py-1.5 pe-3 text-end ${signedRed ? 'text-down' : ''}`}
                            title={data.years.map((y, i) => `${y}: ${value(vals?.[i], ind.unit)}`).join(' · ')}
                          >
                            {value(v, ind.unit)}
                          </td>
                        )
                      })}
                      <td className="py-1.5 text-end">
                        <button
                          type="button"
                          aria-label={`Remove ${r.name}`}
                          className="px-1 text-faint hover:text-fg"
                          onClick={() => setCodes((c) => c.filter((x) => x !== r.code))}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[12px] text-faint">
              Source: {data.source}, updated {data.as_of}
              {data.stale ? ' (saved copy: the IMF did not answer)' : ''}. {projected ? `${year} figures are IMF projections, not results. ` : ''}
              {data.rows.some((r) => r.fiscal_year) && '* India: April-March fiscal years. '}Hover a figure for the three years.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
