import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { searchListings, type Listing } from '../api/listings'
import { cx } from '../lib/cx'
import { labelFor, MARKETS } from '../lib/options'
import { exactMatch, marketFromSuffix } from '../lib/symbolMarket'
import { price } from '../lib/format'
import { Icon, Input, Spinner } from './ui'

const TYPE_LABEL: Record<string, string> = { stock: 'Stock', etf: 'ETF', mf: 'Fund', crypto: 'Crypto' }

/** Typeahead over the full market listing. Free text still works: Enter
 * with nothing highlighted submits whatever was typed (for tickers the
 * listing doesn't know, e.g. global yfinance symbols).
 *
 * With `detect`, it searches every market and reports the market of an
 * exactly typed symbol (RELIANCE -> India, AAPL -> US, BTC-USD -> Crypto)
 * so the page's market picker follows the symbol (lib/symbolMarket.ts). */
export default function SymbolSearch({
  value,
  onChange,
  onSelect,
  onSubmit,
  market = 'all',
  type = 'all',
  exclude = [],
  placeholder = 'Search any stock, ETF or fund',
  autoFocus,
  className,
  detect,
}: {
  value: string
  onChange: (text: string) => void
  onSelect: (row: Listing) => void
  onSubmit?: () => void
  market?: string
  type?: string
  exclude?: string[]
  placeholder?: string
  autoFocus?: boolean
  className?: string
  /** The page's picked market and a setter: called when a typed symbol belongs to another market. */
  detect?: { current: string; onDetect: (market: string) => void }
}) {
  const [results, setResults] = useState<Listing[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(-1)
  // Set when a pick fills the box, so that text change doesn't reopen it.
  const picked = useRef(false)
  const listId = useId()

  const scope = detect || market === 'global' ? 'all' : market
  // Read in the search callback without restarting the search when they change.
  const detectRef = useRef(detect)
  detectRef.current = detect
  const excludeKey = exclude.join(',')

  useEffect(() => {
    const q = value.trim()
    if (picked.current || q.length < 1) {
      picked.current = false
      setResults([])
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    const timer = setTimeout(() => {
      searchListings(q, scope, type, 12, controller.signal)
        .then((rows) => {
          const hidden = excludeKey ? excludeKey.split(',') : []
          setResults(rows.filter((r) => !hidden.includes(r.type)))
          setActive(-1)
          const d = detectRef.current
          const hit = d && (marketFromSuffix(q) ?? exactMatch(q, rows, d.current))
          if (d && hit && hit.market !== d.current) d.onDetect(hit.market)
        })
        .catch(() => {
          if (!controller.signal.aborted) setResults([])
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }, 180)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [value, scope, type, excludeKey])

  function choose(row: Listing) {
    picked.current = true
    setOpen(false)
    setResults([])
    onSelect(row)
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' && results.length) {
      e.preventDefault()
      setOpen(true)
      setActive((i) => (i + 1) % results.length)
    } else if (e.key === 'ArrowUp' && results.length) {
      e.preventDefault()
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1))
    } else if (e.key === 'Enter') {
      if (open && active >= 0 && results[active]) {
        e.preventDefault()
        choose(results[active])
      } else if (onSubmit) {
        e.preventDefault()
        setOpen(false)
        onSubmit()
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const showList = open && value.trim() !== '' && (results.length > 0 || !loading)

  return (
    <div className={cx('relative', className)}>
      <Icon name="search" className="pointer-events-none absolute top-1/2 start-3 h-4 w-4 -translate-y-1/2 text-faint" />
      <Input
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="ps-9"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        spellCheck={false}
      />
      {loading && <Spinner className="absolute top-1/2 end-3 h-3.5 w-3.5 -translate-y-1/2 text-faint" />}
      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-30 mt-1 max-h-80 w-full overflow-auto rounded-lg border border-line-strong bg-raised py-1 shadow-xl"
        >
          {results.length === 0 ? (
            <li className="px-3 py-2 text-xs text-muted">
              No listing matches. {onSubmit ? 'Press Enter to use the typed symbol as-is.' : ''}
            </li>
          ) : (
            results.map((r, i) => (
              <li
                key={`${r.market}:${r.type}:${r.symbol}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => {
                  e.preventDefault()
                  choose(r)
                }}
                onMouseEnter={() => setActive(i)}
                className={cx('flex cursor-pointer items-center gap-3 px-3 py-2', i === active && 'bg-line')}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold">{r.symbol}</span>
                    <span className="rounded bg-canvas px-1.5 text-[12px] text-muted">
                      {labelFor(MARKETS, r.market)} · {TYPE_LABEL[r.type] ?? r.type}
                    </span>
                  </div>
                  <div className="truncate text-xs text-muted">{r.name}</div>
                </div>
                <span className="tabular shrink-0 text-xs text-muted">{price(r.price, r.currency)}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}
