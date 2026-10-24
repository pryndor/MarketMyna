import { useState } from 'react'
import { getDeals, type DealsResponse } from '../api/stocks'
import { DAILY_EVERY, useInsight } from '../lib/insight'
import { DealList } from './OwnershipCard'
import { ScrollBox, Segmented } from './ui'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'

const RANGES = [
  { value: '1', label: 'Latest day' },
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
]

/** Market-wide NSE bulk and block deals. */
export default function DealsCard() {
  const [days, setDays] = useState('1')
  // Deals are published after the close: look for the new day's list.
  const { data, error, at } = useInsight<DealsResponse>(() => getDeals(Number(days)), [days], DAILY_EVERY)

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Big trades (NSE bulk & block deals)</h2>
          <p className="text-xs text-muted">Which funds, promoters and big investors bought or sold large blocks</p>
          <InsightLive at={at} daily="New deals each trading evening" />
        </div>
        <div className="flex items-center gap-2">
          <Segmented size="sm" value={days} onChange={setDays} options={RANGES} />
        </div>
      </div>
      <div className="px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && <InsightLoader className="min-h-56" steps={['Fetching the latest bulk and block deals…', 'Matching deals to companies…', 'Sorting by deal size…']} />}
        {data && (
          <ScrollBox>
            <DealList deals={data} showSymbol />
          </ScrollBox>
        )}
      </div>
    </div>
  )
}
