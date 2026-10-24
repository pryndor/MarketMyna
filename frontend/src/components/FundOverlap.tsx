import { useState } from 'react'
import { getFundOverlap, type FundOverlap as Data } from '../api/listings'
import { errorMessage, num } from '../lib/format'
import SymbolSearch from './SymbolSearch'
import { Skeleton } from './ui'

function reading(overlap: number): string {
  if (overlap >= 50) return 'Heavy overlap: holding both adds little diversification.'
  if (overlap >= 25) return 'Moderate overlap: a good part of the money sits in the same companies.'
  return 'Low overlap: the two funds mostly own different companies.'
}

/** Pick another fund and see how much of the money sits in the same stocks. */
export default function FundOverlap({ code, scheme }: { code: string; scheme: string }) {
  const [query, setQuery] = useState('')
  const [other, setOther] = useState<{ code: string; name: string } | null>(null)
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function compare(otherCode: string, name: string) {
    setOther({ code: otherCode, name })
    setData(null)
    setError(null)
    try {
      setData(await getFundOverlap(code, otherCode))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-semibold">Overlap with another fund</h4>
        <p className="text-xs text-muted">Thinking of holding two funds? See how much of the money would sit in the same companies.</p>
      </div>
      <SymbolSearch
        value={query}
        onChange={setQuery}
        type="mf"
        market="india"
        exclude={[code]}
        placeholder="Search a fund to compare with, e.g. HDFC Flexi Cap"
        onSelect={(row) => {
          setQuery(row.name)
          void compare(String(row.symbol), row.name)
        }}
        className="max-w-xl"
      />
      {error && <p className="text-xs text-down">{error}</p>}
      {other && !data && !error && <Skeleton className="h-24 w-full" />}
      {data && data.status !== 'ok' && <p className="text-xs text-muted">{data.note ?? 'Holdings are not available for one of these funds yet.'}</p>}
      {data && data.status === 'ok' && data.overlap != null && (
        <div className="space-y-3 rounded-lg bg-canvas p-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="tabular text-2xl font-semibold">{num(data.overlap, 1)}%</span>
            <span className="text-sm text-muted">of the money in the same stocks</span>
          </div>
          <p className="text-xs text-muted">
            {reading(data.overlap)} {data.shared_count} stocks in common; {data.only_a} only in {scheme}, {data.only_b} only in {other?.name}.
            {data.note ? ` ${data.note}` : ''}
          </p>
          {data.shared && data.shared.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-faint">
                    <th className="py-1.5 pe-3 text-start font-medium">Shared stock</th>
                    <th className="px-2 py-1.5 text-end font-medium">This fund</th>
                    <th className="py-1.5 ps-2 text-end font-medium">Other fund</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {data.shared.slice(0, 10).map((s) => (
                    <tr key={s.name} className="border-t border-line">
                      <td className="py-1.5 pe-3 text-start">{s.name}</td>
                      <td className="px-2 py-1.5 text-end">{num(s.weight_a, 2)}%</td>
                      <td className="py-1.5 ps-2 text-end">{num(s.weight_b, 2)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-[12px] text-faint">
            From each fund house's monthly portfolio ({data.a.as_of} / {data.b.as_of}). Overlap = for every shared stock, the smaller of the two weights, added up.
          </p>
        </div>
      )}
    </div>
  )
}
