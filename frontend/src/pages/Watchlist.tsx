import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { analyzeLink } from '../api/listings'
import { getWatchlist, type WatchlistDetail, type WatchlistItem } from '../api/watchlists'
import RangeBar from '../components/RangeBar'
import LiveBadge from '../components/LiveBadge'
import { useLiveQuotes } from '../lib/liveQuotes'
import EventCalendar, { type EventSummary } from '../components/EventCalendar'
import ExportMenu from '../components/ExportMenu'
import SymbolSearch from '../components/SymbolSearch'
import { Alert, Button, Card, EmptyState, Icon, Input, PageHeader, Segmented, Skeleton, Stat } from '../components/ui'
import { cx } from '../lib/cx'
import { errorMessage, marketCap, pct, price, trendClass } from '../lib/format'
import { labelFor, MARKETS } from '../lib/options'
import { useWatchlists } from '../lib/watchlists'


// Live prices come from the listing cache; poll gently while the page is open.
const REFRESH_MS = 60_000

type SortKey = 'added' | 'name' | 'price' | 'change_percent' | 'market_cap'

export default function WatchlistPage() {
  const { lists, loaded, loadError, version, load, add, remove, create, rename, destroy } = useWatchlists()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()

  const activeId = Number(params.get('list')) || lists[0]?.id
  const active = lists.find((l) => l.id === activeId) ?? lists[0]

  const [detail, setDetail] = useState<WatchlistDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'added', dir: 1 })
  const [mode, setMode] = useState<'view' | 'new' | 'rename' | 'confirm-delete'>('view')
  const [nameDraft, setNameDraft] = useState('')
  const [find, setFind] = useState('')
  const [events, setEvents] = useState<EventSummary | null>(null)
  const onEvents = useCallback((s: EventSummary) => setEvents(s), [])
  const view = params.get('view') === 'events' ? 'events' : 'stocks'

  function setView(next: 'stocks' | 'events') {
    const p = new URLSearchParams(params)
    if (next === 'events') p.set('view', 'events')
    else p.delete('view')
    setParams(p, { replace: true })
  }

  useEffect(() => {
    if (!loaded) load()
  }, [loaded, load])

  const listId = active?.id
  useEffect(() => {
    if (listId == null) return
    let cancelled = false
    const fetchList = () =>
      getWatchlist(listId)
        .then((d) => {
          if (!cancelled) {
            setDetail(d)
            setError(null)
          }
        })
        .catch((err) => !cancelled && setError(errorMessage(err)))
    fetchList()
    const timer = setInterval(fetchList, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [listId, version])

  const items = useMemo(() => {
    // Before the lists load both ids are undefined, so compare only once detail exists.
    const rows = [...(detail && detail.id === listId ? detail.items : [])]
    const key = sort.key
    if (key === 'added') return sort.dir === 1 ? rows : rows.reverse()
    return rows.sort((a, b) => {
      const av = key === 'name' ? a.name.toLowerCase() : a[key]
      const bv = key === 'name' ? b.name.toLowerCase() : b[key]
      if (av == null) return 1
      if (bv == null) return -1
      return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir
    })
  }, [detail, listId, sort])

  const loadFailed = !loaded && loadError != null

  // "Find in this list": long lists (up to 50 stocks on Pro) need a quick filter.
  const needle = find.trim().toLowerCase()
  const shown = needle
    ? items.filter((i) => i.symbol.toLowerCase().includes(needle) || (i.name ?? '').toLowerCase().includes(needle))
    : items
  // Prices of the rows on screen, refreshed every second (funds: NAV once a day).
  const live = useLiveQuotes(shown)

  const priced = items.filter((i) => i.change_percent != null)
  const gainers = priced.filter((i) => (i.change_percent ?? 0) > 0).length
  const losers = priced.filter((i) => (i.change_percent ?? 0) < 0).length
  const avgChange = priced.length ? priced.reduce((s, i) => s + (i.change_percent ?? 0), 0) / priced.length : null

  function selectList(id: number) {
    setParams({ list: String(id) }, { replace: true })
    setMode('view')
    setFind('')
  }

  async function submitName() {
    const name = nameDraft.trim()
    if (!name) return
    if (mode === 'new') {
      const created = await create(name)
      if (created) selectList(created.id)
    } else if (mode === 'rename' && active) {
      await rename(active.id, name)
    }
    setMode('view')
  }

  function open(item: WatchlistItem) {
    if (item.type === 'mf') {
      // Analyze's Mutual funds section has the full fund analysis.
      navigate(analyzeLink({ symbol: item.symbol, market: 'india', type: 'mf' }))
    } else {
      navigate(analyzeLink(item))
    }
  }

  function header(key: SortKey, label: string, align: 'left' | 'right' = 'right', className?: string) {
    const on = sort.key === key
    return (
      <th className={cx('px-3 py-2.5 font-medium whitespace-nowrap', align === 'left' ? 'text-start' : 'text-end', className)}>
        <button
          type="button"
          onClick={() => setSort({ key, dir: on ? (sort.dir === 1 ? -1 : 1) : key === 'name' || key === 'added' ? 1 : -1 })}
          className={cx('inline-flex items-center gap-1 hover:text-fg', on && 'text-fg')}
        >
          {label}
          <span className="text-[12px]">{on ? (sort.dir === 1 ? '▲' : '▼') : ''}</span>
        </button>
      </th>
    )
  }

  return (
    <div>
      <PageHeader
        title="Watchlist"
        description={
          <>
            Stocks, ETFs and funds you're keeping an eye on. No quantities or money here. For what you own, use{' '}
            <Link to="/portfolio" className="text-accent-fg hover:underline">
              Portfolio
            </Link>
            .
          </>
        }
        actions={
          <>
          <ExportMenu
            title={`Watchlist ${active?.name ?? ''}`}
            disabled={!items.length}
            tables={() => [{
              title: active?.name ?? 'Watchlist',
              columns: [
                { key: 'symbol', label: 'Symbol' }, { key: 'name', label: 'Name' }, { key: 'market', label: 'Market' },
                { key: 'type', label: 'Type' }, { key: 'price', label: 'Price', kind: 'number' },
                { key: 'change_percent', label: 'Change %', kind: 'pct' }, { key: 'market_cap', label: 'Market cap', kind: 'money' },
                { key: 'high_52w', label: '52w high', kind: 'number' }, { key: 'low_52w', label: '52w low', kind: 'number' },
                { key: 'currency', label: 'Currency' }, { key: 'note', label: 'Note' }, { key: 'added_at', label: 'Added', kind: 'date' },
              ],
              rows: items,
            }]}
          />
          <Button
            variant="secondary"
            size="sm"
            icon="plus"
            onClick={() => {
              setNameDraft('')
              setMode('new')
            }}
          >
            New list
          </Button>
          </>
        }
      />


      <PageTabs
        view={view}
        onChange={setView}
        stocks={items.length}
        listName={active?.name}
        events={events}
      />

      <div hidden={view !== 'stocks'}>
      <Card>
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {lists.length > 0 ? (
              <Segmented
                options={lists.map((l) => ({
                  value: String(l.id),
                  label: `${l.name} · ${l.count}`,
                }))}
                value={String(active?.id ?? '')}
                onChange={(v) => selectList(Number(v))}
              />
            ) : (
              <Skeleton className="h-9 w-48" />
            )}
            {active && mode === 'view' && (
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  icon="pencil"
                  onClick={() => {
                    setNameDraft(active.name)
                    setMode('rename')
                  }}
                >
                  Rename
                </Button>
                {lists.length > 1 && (
                  <Button variant="ghost" size="sm" icon="trash" onClick={() => setMode('confirm-delete')}>
                    Delete
                  </Button>
                )}
              </div>
            )}
          </div>

          {(mode === 'new' || mode === 'rename') && (
            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                submitName()
              }}
            >
              <Input
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                placeholder={mode === 'new' ? 'List name, e.g. Banks or Long-term ideas' : 'New name'}
                className="max-w-xs"
                maxLength={60}
                autoFocus
              />
              <Button type="submit" size="sm" disabled={!nameDraft.trim()}>
                {mode === 'new' ? 'Create' : 'Save'}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setMode('view')}>
                Cancel
              </Button>
            </form>
          )}

          {mode === 'confirm-delete' && active && (
            <Alert tone="warn" title={`Delete "${active.name}"?`}>
              <p>Its {active.count} saved items go with it. This can't be undone.</p>
              <div className="mt-2 flex gap-2">
                <Button
                  variant="danger"
                  size="sm"
                  onClick={async () => {
                    await destroy(active.id)
                    setParams({}, { replace: true })
                    setMode('view')
                  }}
                >
                  Delete list
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setMode('view')}>
                  Keep it
                </Button>
              </div>
            </Alert>
          )}

          {active && (
            <SymbolSearch
              value={search}
              onChange={setSearch}
              onSelect={(row) => {
                add(active.id, { symbol: row.symbol, market: row.market, type: row.type, name: row.name })
                setSearch('')
              }}
              placeholder={`Add a stock, ETF or fund to "${active.name}"`}
            />
          )}
        </div>

        {items.length > 0 && (
          <div className="grid grid-cols-2 gap-5 border-t border-line px-5 py-4 sm:grid-cols-4">
            <Stat label="Tracking" value={items.length} />
            <Stat label="Up today" value={<span className="text-up">{gainers}</span>} />
            <Stat label="Down today" value={<span className="text-down">{losers}</span>} />
            <Stat label="Average change" value={<span className={trendClass(avgChange)}>{pct(avgChange)}</span>} />
          </div>
        )}

        {(error || loadFailed) && (
          <div className="px-5 pb-4">
            <Alert title="Could not load watchlist">
              {error ?? loadError}{' '}
              <button type="button" onClick={() => load()} className="font-medium underline">
                Try again
              </button>
            </Alert>
          </div>
        )}

        {loadFailed ? null : detail == null && !error ? (
          <div className="space-y-2 border-t border-line p-5">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="border-t border-line">
            <EmptyState
              icon="star"
              title="Nothing on this list yet"
              description="Search above, or tap the ☆ star next to any row on the Markets page or on a quote in Analyze."
              action={
                <Link to="/">
                  <Button variant="secondary" size="sm" icon="globe">
                    Browse markets
                  </Button>
                </Link>
              }
            />
          </div>
        ) : (
          <>
          {items.length > 0 && (
            <div className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-3">
              {items.length > 10 && (
                <>
              <div className="relative min-w-48 flex-1 sm:max-w-xs">
                <Icon name="search" className="pointer-events-none absolute top-1/2 start-3 h-4 w-4 -translate-y-1/2 text-faint" />
                <Input
                  value={find}
                  onChange={(e) => setFind(e.target.value)}
                  placeholder="Find in this list"
                  aria-label="Find in this list"
                  className="h-8 w-full ps-9 text-xs"
                />
              </div>
              <span className="text-xs text-muted">
                {needle ? `${shown.length} of ${items.length} match` : `${items.length} items · click a column to sort`}
              </span>
                </>
              )}
              <span className="ms-auto">
                <LiveBadge status={live.status} />
              </span>
            </div>
          )}
          {/* Long lists scroll inside the card with the header pinned, so the page stays short. */}
          <div className={cx('overflow-x-auto border-t border-line', items.length > 15 && 'max-h-[70vh] overflow-y-auto')}>
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr className="border-b border-line text-xs text-muted">
                  {header('name', 'Name', 'left')}
                  <th className="hidden px-3 py-2.5 text-start font-medium md:table-cell">Category</th>
                  {header('price', 'Price')}
                  {header('change_percent', 'Chg %')}
                  {header('market_cap', 'Mkt cap', 'right', 'hidden sm:table-cell')}
                  <th className="hidden px-3 py-2.5 text-end font-medium xl:table-cell">52w range</th>
                  <th className="w-10 px-3 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {live.rows.map((item) => (
                  <tr key={item.id} onClick={() => open(item)} className="cursor-pointer hover:bg-raised/50">
                    <td className="max-w-md px-3 py-2.5">
                      <div className="truncate font-medium" title={item.name}>
                        {item.name}
                      </div>
                      <div className="flex items-center gap-1.5 text-xs text-muted">
                        <span className="font-mono">{item.symbol}</span>
                        <span className="text-faint">· {labelFor(MARKETS, item.market)}</span>
                        {item.type !== 'stock' && (
                          <span className="rounded bg-raised px-1 text-[12px] uppercase">{item.type === 'mf' ? 'Fund' : item.type}</span>
                        )}
                      </div>
                    </td>
                    <td className="hidden max-w-52 truncate px-3 py-2.5 text-xs md:table-cell">{item.category ?? '—'}</td>
                    <td className={cx('tabular px-3 py-2.5 text-end', live.flash(item))}>
                      {item.listed ? price(item.price, item.currency) : <span className="text-xs text-faint">open to view</span>}
                    </td>
                    <td className={cx('tabular px-3 py-2.5 text-end', trendClass(item.change_percent))}>{pct(item.change_percent)}</td>
                    <td className="tabular hidden px-3 py-2.5 text-end sm:table-cell">{marketCap(item.market_cap, item.currency)}</td>
                    <td className="hidden px-3 py-2.5 xl:table-cell">
                      <RangeBar low={item.low_52w} high={item.high_52w} value={item.price} />
                    </td>
                    <td className="px-3 py-2.5 text-end">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          if (active) remove(active.id, item)
                        }}
                        className="rounded-md p-1 text-faint hover:bg-down-soft hover:text-down"
                        title={`Remove ${item.symbol}`}
                        aria-label={`Remove ${item.symbol}`}
                      >
                        <Icon name="x" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {needle && shown.length === 0 && (
              <p className="px-5 py-6 text-center text-sm text-muted">Nothing in this list matches "{find.trim()}".</p>
            )}
          </div>
          </>
        )}
      </Card>

      </div>

      <div hidden={view !== 'events'}>
        <EventCalendar className="" onSummary={onEvents} />
      </div>
    </div>
  )
}

/** Watchlist / Upcoming events switch under the page title, so events stay
 * one click away however long the list grows. */
function PageTabs({
  view,
  onChange,
  stocks,
  listName,
  events,
}: {
  view: 'stocks' | 'events'
  onChange: (v: 'stocks' | 'events') => void
  stocks: number
  listName?: string
  events: EventSummary | null
}) {
  const tab = (id: 'stocks' | 'events', icon: 'star' | 'clock', label: string, badge: ReactNode) => (
    <button
      type="button"
      role="tab"
      aria-selected={view === id}
      onClick={() => onChange(id)}
      className={cx(
        '-mb-px flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-4 py-3 text-sm font-medium transition-colors',
        view === id ? 'border-accent text-fg' : 'border-transparent text-muted hover:text-fg',
      )}
    >
      <Icon name={icon} className="h-4 w-4" />
      {label}
      {badge}
    </button>
  )
  return (
    <div role="tablist" aria-label="Watchlist sections" className="no-scrollbar mb-6 flex gap-1 overflow-x-auto border-b border-line">
      {tab(
        'stocks',
        'star',
        listName ?? 'My stocks',
        <span className="rounded-full bg-raised px-2 py-0.5 text-[11px] text-muted">{stocks}</span>,
      )}
      {tab(
        'events',
        'clock',
        'Upcoming events',
        events == null ? null : (
          <span className="flex items-center gap-1">
            <span className="rounded-full bg-raised px-2 py-0.5 text-[11px] text-muted">{events.total}</span>
            {events.today > 0 && (
              <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-medium text-warn">{events.today} today</span>
            )}
          </span>
        ),
      )}
    </div>
  )
}
