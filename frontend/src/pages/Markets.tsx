import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { analyzeLink, getListings, refreshListings, type Listing, type ListingPage, type ShariahStatus } from '../api/listings'
import EnglishToggle from '../components/EnglishToggle'
import { hasChinese, useEnglishNames } from '../lib/english'
import { Alert, Button, Card, EmptyState, Icon, Input, PageHeader, Segmented, Select, Skeleton, Switch } from '../components/ui'
import { cx } from '../lib/cx'
import { compact, errorMessage, marketCap, pct, price, relativeTime, trendClass } from '../lib/format'
import { labelFor, MARKETS, type Option } from '../lib/options'
import { toast } from '../lib/toast'
import RangeBar from '../components/RangeBar'
import LiveBadge from '../components/LiveBadge'
import { useLiveQuotes } from '../lib/liveQuotes'
import MarketInsights from '../components/MarketInsights'
import ExportMenu from '../components/ExportMenu'
import type { ExportTable } from '../lib/exporter'
import WatchButton from '../components/WatchButton'
import { SipDayBadge } from '../components/SipDays'
import ScreenerFilters, { activeFilterCount, CAP_BANDS, FILTER_KEYS, filtersToQuery, W52_PRESETS } from '../components/ScreenerFilters'
import { ChoiceFilter, HeaderFilter, RangeFilter, TextFilter, ValuesFilter } from '../components/ColumnFilter'

// recharts only loads when a fund is opened.

// Labels and hints live in locales/<lang>/markets.json (marketTabs.<value>).
const LISTING_MARKETS = ['india', 'us', 'china_a', 'hong_kong', 'crypto', 'all'] as const
type ListingMarket = (typeof LISTING_MARKETS)[number]
type ListingType = 'all' | 'stock' | 'etf' | 'mf' | 'crypto'
const TYPES_BY_MARKET: Record<string, ListingType[]> = {
  india: ['all', 'stock', 'etf', 'mf'],
  us: ['all', 'stock', 'etf'],
  china_a: ['all', 'stock', 'etf'],
  hong_kong: ['all', 'stock', 'etf'],
  crypto: ['crypto'],
  all: ['all', 'stock', 'etf', 'mf', 'crypto'],
}

const SHARIAH_BADGE: Record<ShariahStatus, string> = {
  halal: 'bg-up-soft text-up',
  doubtful: 'bg-warn-soft text-warn',
  haram: 'bg-down-soft text-down',
  unknown: 'bg-raised text-muted',
}

const PAGE_SIZE = 50
const CLEAR_FILTERS = Object.fromEntries(FILTER_KEYS.map((k) => [k, null]))

type Column = {
  key: string
  label: string
  align?: 'left' | 'right'
  sortable?: boolean
  className?: string
}

function defaultSort(market: string, type: string): string {
  if (market === 'crypto' || type === 'crypto') return 'volume'
  if (type === 'mf' || type === 'etf') return 'name'
  return 'market_cap'
}

const EXPORT_MAX = 5000
// "Ethical only" is remembered per browser, so it stays on for the next visit.
const HALAL_KEY = 'mm_halal_only'

function readHalalPref(): boolean {
  try {
    return localStorage.getItem(HALAL_KEY) === '1'
  } catch {
    return false
  }
}

function writeHalalPref(on: boolean) {
  try {
    if (on) localStorage.setItem(HALAL_KEY, '1')
    else localStorage.removeItem(HALAL_KEY)
  } catch {
    // private window / blocked storage: the toggle still works for this visit
  }
}
// Markets whose ETFs carry a historically best SIP day (src/services/sip_days.py).
const SIP_MARKETS = ['india', 'us', 'hong_kong']

export default function MarketsPage() {
  const { t } = useTranslation('markets')
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()

  const market = params.get('market') ?? 'india'
  const types = TYPES_BY_MARKET[market] ?? ['all']
  const type = types.find((x) => x === params.get('type')) ?? types[0]
  const q = params.get('q') ?? ''
  const sector = params.get('sector') ?? ''
  const plan = params.get('plan') ?? ''
  const option = params.get('option') ?? ''
  const sort = params.get('sort') ?? defaultSort(market, type)
  const order = (params.get('order') ?? (sort === 'name' || sort === 'symbol' ? 'asc' : 'desc')) as 'asc' | 'desc'
  const page = Math.max(0, Number(params.get('page') ?? 0) || 0)
  // Stable key for the advanced filters so the fetch effect re-runs on change.
  const filterKey = FILTER_KEYS.map((k) => params.get(k) ?? '').join('|')
  const filterCount = activeFilterCount(params)
  // Non-halal badges only show while the Shariah filter is in use, to keep the table calm.
  const shariahFilter = Boolean(params.get('sh'))
  const shariahValue = params.get('sh') ?? ''

  const halalOnly = shariahValue === 'halal'
  const shariahScreened = market !== 'crypto'

  function setHalalOnly(on: boolean) {
    writeHalalPref(on)
    update({ sh: on ? 'halal' : null })
  }

  // Bring back a remembered "Ethical only" when the page opens without a Shariah filter of its own.
  useEffect(() => {
    if (!params.get('sh') && shariahScreened && readHalalPref()) update({ sh: 'halal' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [search, setSearch] = useState(q)

  /** Back to the whole market: search, industry, fund plan / option and every filter chip. */
  function clearAll() {
    setSearch('')
    update({ q: null, sector: null, plan: null, option: null, ...CLEAR_FILTERS })
  }
  const [data, setData] = useState<ListingPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [reload, setReload] = useState(0)
  const [showFilters, setShowFilters] = useState(true)

  /** Merge into the URL; any filter change resets to page 0. */
  // The latest URL, for updates that fire later (the debounced search) and
  // must not bring back filters cleared in the meantime.
  const paramsRef = useRef(params)
  paramsRef.current = params

  function update(patch: Record<string, string | null>, keepPage = false) {
    const next = new URLSearchParams(paramsRef.current)
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === '') next.delete(k)
      else next.set(k, v)
    }
    if (!keepPage) next.delete('page')
    paramsRef.current = next
    setParams(next, { replace: true })
  }

  // Debounce the search box into the URL.
  useEffect(() => {
    if (search === q) return
    const t = setTimeout(() => update({ q: search.trim() || null }), 250)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getListings(
      {
        market,
        type,
        q,
        sector,
        plan,
        option,
        sort,
        order,
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        ...filtersToQuery(new URLSearchParams(params)),
      },
      controller.signal,
    )
      .then(setData)
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
    // params is only read for the filter keys, which filterKey tracks.
  }, [market, type, q, sector, plan, option, sort, order, page, reload, filterKey])

  async function refresh() {
    setRefreshing(true)
    try {
      const sources = await refreshListings(market)
      const failed = sources.filter((s) => s.error)
      if (failed.length) toast.error(`${failed.map((s) => s.source).join(', ')}: ${failed[0].error}`)
      else toast.success(t('refreshed'))
      setReload((n) => n + 1)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setRefreshing(false)
    }
  }

  // Every row, funds included, opens its full analysis on the Analyze page.
  function open(row: Listing) {
    navigate(analyzeLink(row))
  }

  function toggleSort(key: string) {
    if (sort === key) update({ sort: key, order: order === 'asc' ? 'desc' : 'asc' })
    else update({ sort: key, order: ['name', 'symbol', 'sector', 'category'].includes(key) ? 'asc' : 'desc' })
  }

  const isFunds = type === 'mf'
  // Prices of the rows on screen, refreshed every second (funds: NAV once a day).
  const live = useLiveQuotes(data?.rows ?? [], !isFunds)
  const showMarket = market === 'all'
  const showSipColumn = isFunds || (type === 'etf' && SIP_MARKETS.includes(market))
  const columns: Column[] = [
    { key: 'name', label: t('col.name'), align: 'left', sortable: true },
    ...(showMarket ? [{ key: 'market', label: t('col.market'), align: 'left' as const }] : []),
    { key: 'category', label: t('col.category'), align: 'left', sortable: true, className: 'hidden md:table-cell' },
    { key: 'price', label: isFunds ? t('col.nav') : t('col.price'), sortable: true },
    ...(showSipColumn ? [{ key: 'sip_day', label: t('col.sipDay'), className: 'hidden sm:table-cell' }] : []),
    ...(isFunds
      ? [{ key: 'nav_date', label: t('col.navDate'), className: 'hidden sm:table-cell' }]
      : [
          { key: 'change_percent', label: t('col.change'), sortable: true },
          { key: 'market_cap', label: t('col.marketCap'), sortable: true, className: 'hidden sm:table-cell' },
          { key: 'volume', label: t('col.volume'), sortable: true, className: 'hidden lg:table-cell' },
          { key: 'range', label: t('col.range'), className: 'hidden xl:table-cell' },
        ]),
  ]
  const english = useEnglishNames(market === 'all' ? 'china_a' : market, live.rows.filter((r) => r.market === 'china_a'))
  const chinese = live.rows.some((r) => hasChinese(r.name))

  /** Excel-style filter menu for a column header (null = not filterable). */
  function columnFilter(c: Column) {
    const listParam = (k: string) => (params.get(k) ?? '').split(',').filter(Boolean)
    const setRange = (lo: string, hi: string) => (a?: number, b?: number) =>
      update({ [lo]: a != null ? String(a) : null, [hi]: b != null ? String(b) : null })
    const header = (active: boolean, body: (close: () => void) => ReactNode) => (
      <HeaderFilter
        label={c.label}
        active={active}
        align={c.align === 'left' ? 'left' : 'right'}
        sortable={c.sortable}
        sorted={sort === c.key ? order : null}
        onSort={(o) => update({ sort: c.key, order: o })}
      >
        {body}
      </HeaderFilter>
    )
    const currencyUnit = market === 'india' ? '₹' : market === 'us' || market === 'crypto' ? '$' : market === 'hong_kong' ? 'HK$' : market === 'china_a' ? '¥' : undefined
    switch (c.key) {
      case 'name':
        return header(Boolean(q), (close) => (
          <TextFilter
            value={q}
            close={close}
            onApply={(v) => {
              setSearch(v)
              update({ q: v || null })
            }}
          />
        ))
      case 'market':
        return header(listParam('mk').length > 0, (close) => (
          <ValuesFilter
            close={close}
            selected={listParam('mk')}
            options={Object.entries(data?.facets.markets ?? {}).map(([m, n]) => ({ value: m, label: marketName(m), count: n }))}
            onApply={(v) => update({ mk: v.join(',') || null })}
          />
        ))
      case 'category':
        return header(listParam('cat').length > 0, (close) => (
          <ValuesFilter
            close={close}
            selected={listParam('cat')}
            options={(data?.facets.categories ?? []).map((f) => ({ value: f.value, count: f.count }))}
            onApply={(v) => update({ cat: v.join(',') || null })}
          />
        ))
      case 'price':
        return header(Boolean(params.get('pmin') || params.get('pmax')), (close) => (
          <RangeFilter close={close} unit={currencyUnit} min={params.get('pmin')} max={params.get('pmax')} onApply={setRange('pmin', 'pmax')} />
        ))
      case 'change_percent':
        return header(Boolean(params.get('cmin') || params.get('cmax') || params.get('chg')), (close) => (
          <RangeFilter
            close={close}
            unit="%"
            hint={t('filter.changeHint')}
            min={params.get('cmin')}
            max={params.get('cmax')}
            presets={[
              { label: t('filters.change.gainers'), min: 0.0001 },
              { label: t('filters.change.losers'), max: -0.0001 },
              { label: t('filters.change.up5'), min: 5 },
              { label: t('filters.change.down5'), max: -5 },
            ]}
            onApply={(a, b) => update({ chg: null, cmin: a != null ? String(a) : null, cmax: b != null ? String(b) : null })}
          />
        ))
      case 'market_cap': {
        const bands = listParam('cap')
        return header(Boolean(params.get('mcmin') || params.get('mcmax') || bands.length), (close) => (
          <RangeFilter
            close={close}
            unit={currencyUnit}
            hint={market === 'india' ? t('filter.capHintIndia') : t('filter.capHint')}
            min={params.get('mcmin')}
            max={params.get('mcmax')}
            onApply={setRange('mcmin', 'mcmax')}
            extra={
              <div className="mb-2 flex flex-wrap gap-1">
                {CAP_BANDS.filter((b) => b.value !== 'mega' || market !== 'india').map((b) => (
                  <button
                    key={b.value}
                    type="button"
                    title={market === 'india' ? b.inr : b.usd}
                    onClick={() => {
                      const next = bands.includes(b.value) ? bands.filter((x) => x !== b.value) : [...bands, b.value]
                      update({ cap: next.join(',') || null })
                    }}
                    className={cx(
                      'rounded-full border px-2 py-0.5 text-xs',
                      bands.includes(b.value) ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:text-fg',
                    )}
                  >
                    {t(`filters.cap.${b.value}`)}
                  </button>
                ))}
              </div>
            }
          />
        ))
      }
      case 'volume':
        return header(Boolean(params.get('vol') || params.get('vmax')), (close) => (
          <RangeFilter
            close={close}
            hint={t('filter.volumeHint')}
            min={params.get('vol')}
            max={params.get('vmax')}
            presets={[{ label: '≥ 100K', min: 1e5 }, { label: '≥ 1M', min: 1e6 }, { label: '≥ 10M', min: 1e7 }]}
            onApply={setRange('vol', 'vmax')}
          />
        ))
      case 'range':
        return header(Boolean(params.get('w52')), (close) => (
          <ChoiceFilter
            close={close}
            value={params.get('w52') ?? ''}
            options={[{ value: '', label: t('filter.any') }, ...W52_PRESETS.map((k) => ({ value: k, label: t(`filters.w52.${k}`), hint: t(`filters.w52.${k}Hint`) }))]}
            onApply={(v) => update({ w52: v || null })}
          />
        ))
      default:
        return null
    }
  }

  /** A new market starts the list fresh: type, industry, sort and every filter reset. */
  const changeMarket = (m: string) =>
    update({ market: m, type: null, sector: null, sort: null, order: null, plan: null, option: null, ...CLEAR_FILTERS })
  const marketName = (m: string) => (LISTING_MARKETS.includes(m as ListingMarket) ? t(`marketTabs.${m as ListingMarket}.label`) : labelFor(MARKETS, m))
  const marketOptions: Option[] = LISTING_MARKETS.map((m) => ({ value: m, label: t(`marketTabs.${m}.label`), hint: t(`marketTabs.${m}.hint`) }))
  const typeOptions: Option[] = types.map((x) => {
    const count = x === 'all' ? undefined : data?.facets.types[x as keyof ListingPage['facets']['types']]
    const name = t(`types.${x}`)
    return { value: x, label: count != null ? `${name} · ${count.toLocaleString()}` : name }
  })
  const sectorOptions: Option[] = [
    { value: '', label: isFunds ? t('allSubCategories') : t('allIndustries') },
    ...(data?.facets.sectors ?? []).map((s) => ({ value: s.value, label: `${s.value} (${s.count})` })),
  ]
  if (sector && !sectorOptions.some((o) => o.value === sector)) sectorOptions.push({ value: sector, label: sector })

  const sources = data?.sources ?? []
  const failed = sources.filter((s) => s.error && !s.count)
  const degraded = sources.filter((s) => s.error && s.count)
  /** Every row matching the current filters (pages of 500, capped at 5,000). */
  async function exportListings(): Promise<ExportTable[]> {
    const query = { market, type, q, sector, plan, option, sort, order, ...filtersToQuery(new URLSearchParams(params)) }
    const rows: Listing[] = []
    for (let offset = 0; offset < Math.min(total, EXPORT_MAX); offset += 500) {
      const page = await getListings({ ...query, offset, limit: 500 })
      rows.push(...page.rows)
      if (page.rows.length < 500) break
    }
    const isFunds = type === 'mf'
    return [{
      title: isFunds ? 'Mutual funds' : 'Listings',
      columns: [
        { key: 'symbol', label: isFunds ? 'Scheme code' : 'Symbol' },
        { key: 'name', label: 'Name' },
        { key: 'market', label: 'Market' },
        { key: 'type', label: 'Type' },
        { key: isFunds ? 'amc' : 'sector', label: isFunds ? 'AMC' : 'Sector' },
        { key: 'category', label: 'Category' },
        { key: 'price', label: isFunds ? 'NAV' : 'Price', kind: 'number' },
        { key: 'change_percent', label: 'Change %', kind: 'pct' },
        { key: 'volume', label: 'Volume', kind: 'number', digits: 0 },
        { key: 'market_cap', label: 'Market cap', kind: 'money' },
        { key: 'high_52w', label: '52w high', kind: 'number' },
        { key: 'low_52w', label: '52w low', kind: 'number' },
        { key: 'currency', label: 'Currency' },
        { key: 'shariah', label: 'Ethical' },
      ],
      rows,
      note: total > EXPORT_MAX ? t('exportNote', { first: EXPORT_MAX.toLocaleString(), total: total.toLocaleString() }) : undefined,
    }]
  }

  const updated = sources.map((s) => s.fetched_at).filter(Boolean).sort()[0]
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div>
      <PageHeader
        title={t('title')}
        description={
          data
            ? `${t('listings', { count: total, n: total.toLocaleString() })}${updated ? ` · ${t('dataUpdated', { ago: relativeTime(updated) })}` : ''}`
            : t('intro')
        }
        actions={
          <>
            {shariahScreened && (
              <Button
                variant={halalOnly ? 'primary' : 'secondary'}
                size="sm"
                icon="check"
                onClick={() => {
                  setHalalOnly(!halalOnly)
                  // The table is below Market insights: bring it into view so the change is visible.
                  document.getElementById('listings')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
                aria-pressed={halalOnly}
                title={t('ethical.buttonTitle')}
              >
                {halalOnly ? t('ethical.onlyOn') : t('ethical.only')}
              </Button>
            )}
            <ExportMenu title={`MarketMyna ${market} listings`} subtitle={q ? t('searchSubtitle', { q }) : undefined} tables={exportListings} disabled={!total} />
            <Button variant="secondary" size="sm" icon="refresh" loading={refreshing} onClick={refresh}>
              {t('refresh')}
            </Button>
          </>
        }
      />

      <MarketInsights
        market={market}
        onCategory={(c) => update({ cat: c, type: market === 'crypto' ? null : 'stock' })}
        markets={marketOptions}
        onMarket={changeMarket}
      />

      <Card id="listings">
        {shariahScreened && (
          <div
            className={cx(
              'rounded-t-xl border-b px-5 py-3',
              halalOnly ? 'border-up/30 bg-up-soft' : 'border-line bg-canvas/40',
            )}
          >
            <Switch
              checked={halalOnly}
              onChange={setHalalOnly}
              label={
                <span className="flex flex-wrap items-center gap-2">
                  <Icon name="check" className="h-4 w-4 text-up" />
                  {t('ethical.only')}
                  {halalOnly && data && (
                    <span className="rounded-md bg-up/15 px-1.5 text-xs font-semibold text-up">
                      {t('ethical.count', { count: total, n: total.toLocaleString() })}
                    </span>
                  )}
                </span>
              }
              description={
                halalOnly
                  ? t('ethical.onDescription')
                  : t('ethical.offDescription')
              }
            />
          </div>
        )}
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <Segmented
              options={marketOptions}
              value={market}
              onChange={changeMarket}
              showHint
            />
            {(chinese || market === 'china_a') && <EnglishToggle loading={english.loading} className="mt-1" />}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {types.length > 1 && (
              <Segmented
                options={typeOptions}
                value={type}
                size="sm"
                onChange={(t) => update({ type: t === 'all' ? null : t, sector: null, sort: null, order: null, plan: null, option: null, ...CLEAR_FILTERS })}
              />
            )}
            <div className="relative min-w-56 flex-1">
              <Icon name="search" className="pointer-events-none absolute top-1/2 start-3 h-4 w-4 -translate-y-1/2 text-faint" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={isFunds ? t('searchFunds') : t('searchStocks')}
                className="ps-9"
                spellCheck={false}
              />
            </div>
            <Select
              options={sectorOptions}
              value={sector}
              onChange={(e) => update({ sector: e.target.value || null })}
              className="w-auto max-w-64"
            />
            <Button
              variant={filterCount ? 'primary' : 'secondary'}
              icon="filter"
              onClick={() => setShowFilters((v) => !v)}
              aria-expanded={showFilters}
            >
              {t('filtersButton')}{filterCount ? ` · ${filterCount}` : ''}
            </Button>
            {(filterCount > 0 || q || sector || plan || option) && (
              <Button variant="ghost" icon="x" onClick={clearAll} title={t('clearTitle')}>
                {t('clear')}
              </Button>
            )}
            {isFunds && (
              <>
                <Select
                  options={[
                    { value: '', label: t('plan.both') },
                    { value: 'Direct', label: t('plan.direct') },
                    { value: 'Regular', label: t('plan.regular') },
                  ]}
                  value={plan}
                  onChange={(e) => update({ plan: e.target.value || null })}
                  className="w-auto"
                />
                <Select
                  options={[
                    { value: '', label: t('option.any') },
                    { value: 'Growth', label: t('option.growth') },
                    { value: 'IDCW', label: 'IDCW' },
                  ]}
                  value={option}
                  onChange={(e) => update({ option: e.target.value || null })}
                  className="w-auto"
                />
              </>
            )}
          </div>
        </div>

        {showFilters && (
          <ScreenerFilters
            params={params}
            update={update}
            categories={data?.facets.categories ?? []}
            isFunds={isFunds}
            showCap={market !== 'crypto'}
            showShariah={market !== 'crypto'}
            shariahCounts={data?.facets.shariah}
            showSip={type === 'mf' || (type === 'etf' && SIP_MARKETS.includes(market))}
            currency={market === 'india' ? 'INR' : market === 'us' || market === 'crypto' ? 'USD' : null}
          />
        )}

        {failed.map((s) => (
          <div key={s.source} className="px-5 pb-4">
            <Alert tone="warn" title={t('unavailable', { market: marketName(s.market) })}>
              {s.error}
            </Alert>
          </div>
        ))}
        {degraded.map((s) => (
          <div key={s.source} className="px-5 pb-4">
            <Alert tone="accent" title={t('partial', { market: marketName(s.market) })}>
              {s.error}. {t('retrying')}
            </Alert>
          </div>
        ))}
        {error && (
          <div className="px-5 pb-4">
            <Alert title={t('loadError')}>{error}</Alert>
          </div>
        )}

        {!isFunds && (data?.rows.length ?? 0) > 0 && (
          <div className="border-t border-line px-5 py-2">
            <LiveBadge status={live.status} />
          </div>
        )}
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="w-8 px-1 py-2.5" aria-label={t('col.watch')} />
                <th className="w-12 px-3 py-2.5 text-end font-medium">#</th>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    className={cx('px-3 py-2.5 font-medium whitespace-nowrap', c.align === 'left' ? 'text-start' : 'text-end', c.className)}
                  >
                    <span className={cx('inline-flex items-center gap-1', c.align !== 'left' && 'flex-row-reverse')}>
                      {c.sortable ? (
                        <button
                          type="button"
                          onClick={() => toggleSort(c.key)}
                          className={cx('inline-flex items-center gap-1 hover:text-fg', sort === c.key && 'text-fg')}
                        >
                          {c.label}
                          <span className="text-[12px]">{sort === c.key ? (order === 'asc' ? '▲' : '▼') : ''}</span>
                        </button>
                      ) : (
                        c.label
                      )}
                      {columnFilter(c)}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className={cx('divide-y divide-line', loading && data && 'opacity-60')}>
              {loading && !data
                ? Array.from({ length: 12 }, (_, i) => (
                    <tr key={i}>
                      <td colSpan={columns.length + 2} className="px-3 py-2.5">
                        <Skeleton className="h-5 w-full" />
                      </td>
                    </tr>
                  ))
                : live.rows.map((row, i) => (
                    <tr
                      key={`${row.market}:${row.type}:${row.symbol}`}
                      onClick={() => open(row)}
                      className="cursor-pointer hover:bg-raised/50"
                    >
                      <td className="px-1 py-2.5 text-center">
                        <WatchButton item={{ symbol: row.symbol, market: row.market, type: row.type, name: row.name }} />
                      </td>
                      <td className="tabular px-3 py-2.5 text-end text-xs text-faint">{page * PAGE_SIZE + i + 1}</td>
                      <td className="max-w-md px-3 py-2.5">
                        <div className="truncate font-medium" title={row.name}>
                          {english.name(row.symbol, row.name)}
                        </div>
                        <div className="flex items-center gap-1.5 text-xs text-muted">
                          <span className="font-mono">{row.symbol}</span>
                          {row.exchange && <span className="text-faint">· {row.exchange}</span>}
                          {row.name_local && row.name_local !== row.name && <span className="truncate text-faint">· {row.name_local}</span>}
                          {english.on && hasChinese(row.name) && english.name(row.symbol, row.name) !== row.name && (
                            <span className="truncate text-faint">· {row.name}</span>
                          )}
                          {type === 'all' && row.type !== 'stock' && (
                            <span className="rounded bg-raised px-1 text-[12px] uppercase">{row.type === 'mf' ? t('fund') : row.type}</span>
                          )}
                          {row.shariah && (row.shariah === 'halal' || shariahFilter) && (
                            <span
                              className={cx('rounded px-1 text-[12px] font-medium', SHARIAH_BADGE[row.shariah])}
                              title={row.shariah_reason}
                            >
                              {t(`badge.${row.shariah}`)}
                            </span>
                          )}
                        </div>
                      </td>
                      {showMarket && <td className="px-3 py-2.5 text-xs text-muted">{marketName(row.market)}</td>}
                      <td className="hidden max-w-52 px-3 py-2.5 md:table-cell">
                        <div
                          className="truncate text-xs"
                          title={row.category_inferred ? t('categoryGuessed') : undefined}
                        >
                          {row.category ?? '—'}
                          {row.category_inferred && row.type === 'stock' && <span className="text-faint">*</span>}
                        </div>
                        {row.sector && row.sector !== row.category && (
                          <div className="truncate text-xs text-faint" title={row.sector}>
                            {row.sector}
                          </div>
                        )}
                      </td>
                      <td className={cx('tabular px-3 py-2.5 text-end', live.flash(row))}>{price(row.price, row.currency)}</td>
                      {showSipColumn && (
                        <td className="hidden px-3 py-2.5 text-end sm:table-cell">
                          <SipDayBadge day={row.sip_day} edge={row.sip_edge} spread={row.sip_spread} />
                        </td>
                      )}
                      {isFunds ? (
                        <td className="tabular hidden px-3 py-2.5 text-end text-xs text-muted sm:table-cell">{row.nav_date ?? '—'}</td>
                      ) : (
                        <>
                          <td className={cx('tabular px-3 py-2.5 text-end', trendClass(row.change_percent))}>{pct(row.change_percent)}</td>
                          <td className="tabular hidden px-3 py-2.5 text-end sm:table-cell">{marketCap(row.market_cap, row.currency)}</td>
                          <td className="tabular hidden px-3 py-2.5 text-end text-muted lg:table-cell">{compact(row.volume)}</td>
                          <td className="hidden px-3 py-2.5 xl:table-cell">
                            <RangeBar low={row.low_52w} high={row.high_52w} value={row.price} />
                          </td>
                        </>
                      )}
                    </tr>
                  ))}
            </tbody>
          </table>
          {!loading && data && data.rows.length === 0 && (
            <EmptyState
              icon="search"
              title={t('empty.title')}
              description={failed.length ? t('empty.noData') : t('empty.tryAgain')}
            />
          )}
        </div>

        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3 text-xs text-muted">
            <span className="tabular">
              {t('pager.range', {
                from: (page * PAGE_SIZE + 1).toLocaleString(),
                to: Math.min(total, (page + 1) * PAGE_SIZE).toLocaleString(),
                total: total.toLocaleString(),
              })}
            </span>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => update({ page: null }, true)}>
                {t('pager.first')}
              </Button>
              <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => update({ page: String(page - 1) }, true)}>
                {t('pager.prev')}
              </Button>
              <span className="tabular px-2">
                {t('pager.page', { page: page + 1, pages: pages.toLocaleString() })}
              </span>
              <Button variant="ghost" size="sm" disabled={page >= pages - 1} onClick={() => update({ page: String(page + 1) }, true)}>
                {t('pager.next')}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
