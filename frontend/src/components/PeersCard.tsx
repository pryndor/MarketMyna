import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { compareLink, getPeers, type PeerResult } from '../api/compare'
import { compact, errorMessage, num, pct, trendClass } from '../lib/format'
import { Card, CardBody, CardHeader, Icon, Skeleton } from './ui'

/** Same-industry companies of similar size, with one-click comparison. */
export default function PeersCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<PeerResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    getPeers(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (market === 'crypto') return null
  const me = { symbol: symbol.toUpperCase(), market }
  const all = data ? [me, ...data.peers.slice(0, 4).map((p) => ({ symbol: p.symbol, market }))] : []

  return (
    <Card id="section-peers" section="Peers">
      <CardHeader
        title="Peers"
        description={data?.basis ?? 'Same-industry companies of similar size'}
        icon="compare"
        actions={
          data && data.peers.length > 0 ? (
            <Link
              to={compareLink(all)}
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-fg"
            >
              <Icon name="compare" className="h-3.5 w-3.5" />
              Compare {all.length}
            </Link>
          ) : undefined
        }
      />
      <CardBody>
        {error ? (
          <p className="text-sm text-muted">Peers unavailable: {error}</p>
        ) : !data ? (
          <Skeleton className="h-40 w-full" />
        ) : data.peers.length === 0 ? (
          <p className="text-sm text-muted">{data.note ?? 'No peers found.'}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="tabular w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 text-start font-medium">Company</th>
                  <th className="px-2 py-2 text-end font-medium">Mkt cap</th>
                  <th className="px-2 py-2 text-end font-medium">P/E</th>
                  <th className="hidden px-2 py-2 text-end font-medium sm:table-cell">Day</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.peers.map((p) => (
                  <tr key={p.symbol}>
                    <td className="max-w-[12rem] py-2">
                      <Link to={`/analyze?symbol=${encodeURIComponent(p.symbol)}&market=${market}`} className="block truncate hover:text-accent-fg" title={p.name ?? p.symbol}>
                        <span className="font-mono text-xs font-medium">{p.symbol}</span>{' '}
                        <span className="hidden text-xs text-muted sm:inline">{p.name}</span>
                      </Link>
                    </td>
                    <td className="px-2 py-2 text-end">{compact(p.market_cap)}</td>
                    <td className="px-2 py-2 text-end">{num(p.pe, 1)}</td>
                    <td className={`hidden px-2 py-2 text-end sm:table-cell ${trendClass(p.change_percent)}`}>{pct(p.change_percent, 1)}</td>
                    <td className="py-2 text-end">
                      <Link to={compareLink([me, { symbol: p.symbol, market }])} className="text-xs text-muted hover:text-accent-fg" title={`Compare ${me.symbol} with ${p.symbol}`}>
                        vs
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
