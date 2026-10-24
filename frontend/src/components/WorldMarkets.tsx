import { getWorldMarkets, type WorldItem, type WorldMarkets as Data } from '../api/macro'
import { cx } from '../lib/cx'
import { num, pct, signed, trendClass } from '../lib/format'
import { liveEvery, useFlash, useInsight } from '../lib/insight'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'
import MiniSparkline from './MiniSparkline'

const GROUPS: Array<{ key: WorldItem['group']; label: string }> = [
  { key: 'asia', label: 'Asia-Pacific' },
  { key: 'europe', label: 'Europe' },
  { key: 'americas', label: 'Americas' },
  { key: 'fx', label: 'Currencies' },
  { key: 'yields', label: 'US Treasury yields' },
  { key: 'volatility', label: 'Volatility' },
]

function change(item: WorldItem, value: number | null): string {
  return item.change_unit === 'points' ? signed(value, 2) : pct(value, 1)
}

function price(item: WorldItem): string {
  if (item.group === 'yields') return `${num(item.price, 2)}%`
  if (item.group === 'fx') return num(item.price, item.price < 10 ? 4 : 2)
  return num(item.price, 2)
}

/** World indices, currencies, US yields and fear gauges in one place. */
export default function WorldMarkets() {
  // Latest prices patched in by the server every minute; somewhere is always trading.
  const { data, error, at } = useInsight((signal) => getWorldMarkets(signal), [], liveEvery(60_000))
  const flash = useFlash(Object.fromEntries((data?.items ?? []).map((i) => [i.key, i.price])))

  return (
    <div>
      <div className="px-5 py-3">
        <h2 className="text-sm font-semibold">World markets</h2>
        <p className="text-xs text-muted">Major indices by region, currencies, US yields and fear gauges</p>
        {data && <InsightLive live={data.live} at={at} />}
      </div>
      <div className="space-y-4 px-5 pb-4">
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && (
          <InsightLoader className="min-h-56" steps={['Fetching world indices…', 'Fetching currencies and yields…', 'Reading fear gauges…']} />
        )}
        {data && <Mood data={data} />}
        {data &&
          GROUPS.map((g) => {
            const rows = data.items.filter((i) => i.group === g.key)
            if (!rows.length) return null
            return (
              <div key={g.key}>
                <div className="mb-2 text-xs font-medium text-muted">{g.label}</div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {rows.map((i) => (
                    <Tile key={i.key} item={i} flash={flash(i.key)} />
                  ))}
                </div>
              </div>
            )
          })}
        {data && (
          <p className="text-[12px] text-faint">
            Source: {data.source}.{' '}
            {data.live?.live
              ? 'Latest prices refresh every minute and can lag up to 15 min; 1-day changes are against the previous close.'
              : "Daily closes, delayed; each market's last close is in its own time zone."}
            {data.failed.length > 0 && ` Unavailable now: ${data.failed.join(', ')}.`}
          </p>
        )}
      </div>
    </div>
  )
}

function Mood({ data }: { data: Data }) {
  const vt = data.vix_term
  const fg = data.crypto_mood
  if (!vt && !fg) return null
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {vt && (
        <div className="rounded-lg bg-canvas px-3 py-2">
          <div className="text-xs text-muted">VIX term structure</div>
          <div className="flex items-baseline gap-2">
            <span className={`text-lg font-semibold ${vt.shape === 'backwardation' ? 'text-down' : 'text-up'}`}>
              {vt.shape === 'backwardation' ? 'Backwardation' : 'Contango'}
            </span>
            <span className="tabular text-xs text-faint">
              VIX {num(vt.vix, 2)} / 3-month {num(vt.vix3m, 2)} = {num(vt.ratio, 2)}
            </span>
          </div>
          <p className="text-[12px] text-muted">{vt.note}</p>
        </div>
      )}
      {fg && (
        <div className="rounded-lg bg-canvas px-3 py-2">
          <div className="flex justify-between text-xs text-muted">
            <span>Crypto fear &amp; greed</span>
            <span className="text-faint">0 fear · 100 greed</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="tabular text-lg font-semibold">{fg.value}</span>
            <span className="text-sm">{fg.label}</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-line">
            <div className="h-1.5 rounded-full bg-accent" style={{ width: `${fg.value}%` }} />
          </div>
          <p className="tabular mt-1 text-[12px] text-faint">
            {fg.week_ago != null && `Week ago ${fg.week_ago}`}
            {fg.month_ago != null && ` · month ago ${fg.month_ago}`}
          </p>
        </div>
      )}
    </div>
  )
}

function Tile({ item, flash }: { item: WorldItem; flash: string }) {
  const s = item.spark
  const up = s.length < 2 || s[s.length - 1] >= s[0]
  return (
    <div className={cx('rounded-lg bg-canvas px-3 py-2', flash)} title={`${item.note} · as of ${item.as_of}`}>
      <div className="flex justify-between gap-2 text-xs text-muted">
        <span className="truncate">{item.label}</span>
        <span className="shrink-0 truncate text-faint">{item.group === 'fx' || item.group === 'yields' ? '' : item.note}</span>
      </div>
      <div className="flex items-end justify-between gap-2">
        <div className="min-w-0">
          <div className="tabular text-lg font-semibold">{price(item)}</div>
          <div className="tabular whitespace-nowrap text-[11px] text-faint">
            1d <span className={trendClass(item.change_1d)}>{change(item, item.change_1d)}</span> · 1y{' '}
            <span className={trendClass(item.change_1y)}>{change(item, item.change_1y)}</span>
          </div>
        </div>
        <MiniSparkline values={s} up={up} />
      </div>
    </div>
  )
}
