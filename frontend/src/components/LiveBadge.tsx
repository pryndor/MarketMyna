import type { LiveStatus } from '../lib/liveQuotes'
import { useTranslation } from 'react-i18next'
import { cx } from '../lib/cx'

/** "● Live · updated 3s ago" above a table, with where prices come from. */
export default function LiveBadge({ status }: { status: LiveStatus }) {
  const { t } = useTranslation('app')
  const markets = Object.values(status.markets)
  if (!markets.length) return null
  // Open by the clock, but no trade for an hour: a holiday or a halt.
  const quiet = (m: (typeof markets)[number]) => m.last_trade != null && Date.now() / 1000 - m.last_trade > 3600
  const open = markets.some((m) => m.open && !quiet(m))
  const holiday = !open && markets.some((m) => m.open && quiet(m))
  const error = markets.find((m) => m.error)?.error
  const sources = [...new Set(markets.map((m) => m.source))].join(' · ')
  const age = status.updated
  return (
    <span
      className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted"
      title={t('live.prices', { sources })}
    >
      <span className={cx('inline-flex items-center gap-1.5 font-medium', open ? 'text-up' : 'text-muted')}>
        <span className={cx('h-2 w-2 rounded-full', open ? 'animate-pulse bg-up' : 'bg-faint')} />
        {open ? t('live.live') : holiday ? t('live.noTrading') : t('live.closed')}
      </span>
      <span>
        {age == null
          ? t('live.connecting')
          : open
            ? age < 1
              ? t('live.updatedNow')
              : t('live.updatedAgo', { count: Math.round(age) })
            : t('live.lastTraded')}
      </span>
      <span className="hidden text-faint sm:inline">· {sources}</span>
      {error && <span className="text-warn">· {error}</span>}
    </span>
  )
}
