import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { ListingQuery, ShariahStatus, SipEdge } from '../api/listings'
import { cx } from '../lib/cx'
import { Icon, Input } from './ui'

/** URL keys owned by the advanced filter panel and the column filters
 * (cmin/cmax day change, mcmin/mcmax market cap, vmax volume, mk markets). */
export const FILTER_KEYS = ['cat', 'cap', 'sh', 'sip', 'pmin', 'pmax', 'chg', 'w52', 'vol', 'cmin', 'cmax', 'mcmin', 'mcmax', 'vmax', 'mk'] as const

const PRICE_BANDS: Array<{ min?: number; max?: number }> = [
  { max: 50 },
  { min: 50, max: 100 },
  { min: 100, max: 500 },
  { min: 500, max: 1000 },
  { min: 1000, max: 5000 },
  { min: 5000 },
]

// Chip labels and hints: locales/<lang>/markets.json under "filters".
export const CAP_BANDS = [
  { value: 'mega', inr: '≥ $200B', usd: '≥ $200B' },
  { value: 'large', inr: '≥ ₹20,000 Cr', usd: '$10B – 200B' },
  { value: 'mid', inr: '₹5,000 – 20,000 Cr', usd: '$2B – 10B' },
  { value: 'small', inr: '₹500 – 5,000 Cr', usd: '$300M – 2B' },
  { value: 'micro', inr: '< ₹500 Cr', usd: '< $300M' },
] as const

const CHANGE_PRESETS = {
  gainers: { min: 0.0001 },
  losers: { max: -0.0001 },
  up5: { min: 5 },
  down5: { max: -5 },
} as const satisfies Record<string, { min?: number; max?: number }>

export const W52_PRESETS = ['high', 'low'] as const

const SHARIAH_OPTIONS: ShariahStatus[] = ['halal', 'doubtful', 'haram', 'unknown']

const SIP_EDGE_OPTIONS: SipEdge[] = ['consistent', 'no_edge', 'negligible', 'short']

const VOLUME_PRESETS: Record<string, string> = { '10000': '≥ 10K', '100000': '≥ 100K', '1000000': '≥ 1M' }

/** "1,000 – 5,000" for a price band, with the currency symbol when there is one. */
function bandLabel(t: (key: 'filters.price.under' | 'filters.price.above', o: { n: string }) => string, b: { min?: number; max?: number }, symbol: string) {
  const n = (v: number) => `${symbol}${v.toLocaleString('en-US')}`
  if (b.min == null) return t('filters.price.under', { n: n(b.max!) })
  if (b.max == null) return t('filters.price.above', { n: n(b.min) })
  return `${n(b.min)} – ${n(b.max)}`
}

function list(value: string | null): string[] {
  return value ? value.split(',').filter(Boolean) : []
}

function numOrUndef(value: string | null): number | undefined {
  if (value == null || value === '') return undefined
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

/** URL params -> /listings query params. */
export function filtersToQuery(params: URLSearchParams): Partial<ListingQuery> {
  const chg: { min?: number; max?: number } | undefined = CHANGE_PRESETS[params.get('chg') as keyof typeof CHANGE_PRESETS]
  const w52 = params.get('w52')
  return {
    category: list(params.get('cat')).join(',') || undefined,
    cap: list(params.get('cap')).join(',') || undefined,
    shariah: list(params.get('sh')).join(',') || undefined,
    sip_edge: list(params.get('sip')).join(',') || undefined,
    price_min: numOrUndef(params.get('pmin')),
    price_max: numOrUndef(params.get('pmax')),
    change_min: numOrUndef(params.get('cmin')) ?? chg?.min,
    change_max: numOrUndef(params.get('cmax')) ?? chg?.max,
    near_high: w52 === 'high' ? 5 : undefined,
    near_low: w52 === 'low' ? 5 : undefined,
    min_volume: numOrUndef(params.get('vol')),
    max_volume: numOrUndef(params.get('vmax')),
    min_cap: numOrUndef(params.get('mcmin')),
    max_cap: numOrUndef(params.get('mcmax')),
    markets: list(params.get('mk')).join(',') || undefined,
  }
}

export function activeFilterCount(params: URLSearchParams): number {
  let n = list(params.get('cat')).length + list(params.get('cap')).length + list(params.get('sh')).length + list(params.get('sip')).length
  if (params.get('pmin') || params.get('pmax')) n += 1
  for (const k of ['chg', 'w52', 'vol']) if (params.get(k)) n += 1
  if (params.get('cmin') || params.get('cmax')) n += 1
  if (params.get('mcmin') || params.get('mcmax')) n += 1
  if (params.get('vmax')) n += 1
  n += list(params.get('mk')).length
  return n
}

function Chip({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={cx(
        'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
        active ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:border-line-strong hover:text-fg',
      )}
    >
      {children}
    </button>
  )
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-4">
      <div className="pt-1">
        <div className="text-xs font-medium text-muted">{label}</div>
        {hint && <div className="text-xs text-faint">{hint}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">{children}</div>
    </div>
  )
}

/** Screener-style filter panel. All state lives in the URL (see FILTER_KEYS). */
export default function ScreenerFilters({
  params,
  update,
  categories,
  isFunds,
  currency,
  showCap = true,
  shariahCounts,
  showShariah = true,
  showSip = false,
}: {
  params: URLSearchParams
  update: (patch: Record<string, string | null>) => void
  categories: Array<{ value: string; count: number }>
  isFunds: boolean
  /** 'INR' | 'USD' | ... or null when several markets are mixed. */
  currency: string | null
  /** Crypto has no market cap in the listing, so the band chips would only empty the table. */
  showCap?: boolean
  shariahCounts?: Partial<Record<ShariahStatus, number>>
  /** Crypto is not screened, so the chips would only show "Unclassified". */
  showShariah?: boolean
  /** Mutual funds and ETFs: filter by the historically best SIP day label. */
  showSip?: boolean
}) {
  const { t } = useTranslation('markets')
  const cats = list(params.get('cat'))
  const caps = list(params.get('cap'))
  const shariah = list(params.get('sh'))
  const sip = list(params.get('sip'))
  const pmin = params.get('pmin') ?? ''
  const pmax = params.get('pmax') ?? ''
  const symbol = currency === 'INR' ? '₹' : currency === 'USD' ? '$' : ''

  // Custom price inputs are local until blur/Enter so typing doesn't refetch per key.
  const [minText, setMinText] = useState(pmin)
  const [maxText, setMaxText] = useState(pmax)
  useEffect(() => setMinText(pmin), [pmin])
  useEffect(() => setMaxText(pmax), [pmax])

  function toggle(key: 'cat' | 'cap' | 'sh' | 'sip', current: string[], value: string) {
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
    update({ [key]: next.join(',') || null })
  }

  function commitPrice() {
    const clean = (s: string) => (s.trim() === '' || !Number.isFinite(Number(s)) ? null : String(Number(s)))
    update({ pmin: clean(minText), pmax: clean(maxText) })
  }

  // Keep selected categories visible even when the current result set has none.
  const categoryOptions = [...categories]
  for (const c of cats) if (!categoryOptions.some((o) => o.value === c)) categoryOptions.push({ value: c, count: 0 })

  return (
    <div className="space-y-4 border-t border-line bg-canvas/40 px-5 py-4">
      <Row label={isFunds ? t('filters.fundType') : t('filters.category')} hint={t('filters.pickAny')}>
        {categoryOptions.length === 0 && <span className="text-xs text-faint">{t('filters.noCategories')}</span>}
        {categoryOptions.map((c) => (
          <Chip key={c.value} active={cats.includes(c.value)} onClick={() => toggle('cat', cats, c.value)}>
            {c.value} <span className="text-faint">{c.count.toLocaleString()}</span>
          </Chip>
        ))}
      </Row>

      {showShariah && (
        <Row label={t('filters.ethical')} hint={t('filters.ethicalHint')}>
          {SHARIAH_OPTIONS.map((o) => (
            <Chip key={o} active={shariah.includes(o)} onClick={() => toggle('sh', shariah, o)} title={t(`filters.shariah.${o}Hint`)}>
              {t(`filters.shariah.${o}`)} <span className="text-faint">{(shariahCounts?.[o] ?? 0).toLocaleString()}</span>
            </Chip>
          ))}
        </Row>
      )}

      {showSip && (
        <Row label={t('filters.sip')} hint={t('filters.sipHint')}>
          {SIP_EDGE_OPTIONS.map((o) => (
            <Chip key={o} active={sip.includes(o)} onClick={() => toggle('sip', sip, o)} title={t(`filters.sipEdge.${o}Hint`)}>
              {t(`filters.sipEdge.${o}`)}
            </Chip>
          ))}
        </Row>
      )}

      <Row label={isFunds ? t('filters.nav') : t('filters.price.label')} hint={symbol ? t('filters.price.in', { symbol }) : t('filters.price.eachCurrency')}>
        {PRICE_BANDS.map((b) => {
          const active = pmin === (b.min != null ? String(b.min) : '') && pmax === (b.max != null ? String(b.max) : '')
          return (
            <Chip
              key={`${b.min}-${b.max}`}
              active={active}
              onClick={() =>
                active
                  ? update({ pmin: null, pmax: null })
                  : update({ pmin: b.min != null ? String(b.min) : null, pmax: b.max != null ? String(b.max) : null })
              }
            >
              {bandLabel(t, b, symbol)}
            </Chip>
          )
        })}
        <span className="ms-1 flex items-center gap-1.5">
          <Input
            value={minText}
            onChange={(e) => setMinText(e.target.value)}
            onBlur={commitPrice}
            onKeyDown={(e) => e.key === 'Enter' && commitPrice()}
            placeholder={t('filters.min')}
            inputMode="decimal"
            className="h-7 w-20 text-xs"
            aria-label={t('filters.minPrice')}
          />
          <span className="text-faint">–</span>
          <Input
            value={maxText}
            onChange={(e) => setMaxText(e.target.value)}
            onBlur={commitPrice}
            onKeyDown={(e) => e.key === 'Enter' && commitPrice()}
            placeholder={t('filters.max')}
            inputMode="decimal"
            className="h-7 w-20 text-xs"
            aria-label={t('filters.maxPrice')}
          />
        </span>
      </Row>

      {!isFunds && (
        <>
          {showCap && <Row label={t('filters.marketCap')}>
            {/* No Indian company is mega-sized yet, so the chip would always be empty there. */}
            {CAP_BANDS.filter((b) => b.value !== 'mega' || currency !== 'INR').map((b) => (
              <Chip
                key={b.value}
                active={caps.includes(b.value)}
                onClick={() => toggle('cap', caps, b.value)}
                title={currency === 'INR' ? b.inr : currency === 'USD' ? b.usd : `${b.inr} · ${b.usd}`}
              >
                {t(`filters.cap.${b.value}`)}
                <span className="ms-1 text-faint">{currency === 'INR' ? b.inr : b.usd}</span>
              </Chip>
            ))}
          </Row>}

          <Row label={t('filters.today')}>
            {(Object.keys(CHANGE_PRESETS) as Array<keyof typeof CHANGE_PRESETS>).map((key) => (
              <Chip key={key} active={params.get('chg') === key} onClick={() => update({ chg: params.get('chg') === key ? null : key })}>
                {t(`filters.change.${key}`)}
              </Chip>
            ))}
          </Row>

          <Row label={t('filters.w52.label')}>
            {W52_PRESETS.map((key) => (
              <Chip
                key={key}
                active={params.get('w52') === key}
                onClick={() => update({ w52: params.get('w52') === key ? null : key })}
                title={t(`filters.w52.${key}Hint`)}
              >
                {t(`filters.w52.${key}`)}
              </Chip>
            ))}
          </Row>

          <Row label={t('filters.volume')} hint={t('filters.volumeHint')}>
            {Object.entries(VOLUME_PRESETS).map(([value, label]) => (
              <Chip key={value} active={params.get('vol') === value} onClick={() => update({ vol: params.get('vol') === value ? null : value })}>
                {label}
              </Chip>
            ))}
          </Row>
        </>
      )}

      {activeFilterCount(params) > 0 && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => update(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])))}
            className="inline-flex items-center gap-1 text-xs text-muted hover:text-fg"
          >
            <Icon name="x" className="h-3 w-3" /> {t('filters.clearAll')}
          </button>
        </div>
      )}
    </div>
  )
}
