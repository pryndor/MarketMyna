import { apiClient } from './client'

export type ListingType = 'stock' | 'etf' | 'mf' | 'crypto'

/** Shariah screen status (see src/data/shariah.py). For stocks, halal
 * means the business activity passes; ratios are on the stock page. */
export type ShariahStatus = 'halal' | 'doubtful' | 'haram' | 'unknown'
/** Historically best SIP day label (src/services/sip_days.py). */
export type SipEdge = 'consistent' | 'no_edge' | 'short' | 'negligible'

export interface Listing {
  symbol: string
  name: string
  market: string
  type: ListingType
  exchange: string | null
  sector: string | null
  price: number | null
  change: number | null
  change_percent: number | null
  volume: number | null
  market_cap: number | null
  high_52w: number | null
  low_52w: number | null
  currency: string | null
  /** Local-language name (Chinese for China A / Hong Kong). */
  name_local?: string
  /** Broad cross-market category (Technology, Agriculture, ...). */
  category?: string
  /** True when the category was guessed from the company name. */
  category_inferred?: boolean
  shariah?: ShariahStatus
  shariah_reason?: string
  // Funds and ETFs: historically best SIP day over the longest window
  sip_day?: number
  sip_edge?: SipEdge
  sip_spread?: number
  // Mutual funds
  amc?: string
  fund_group?: string
  plan?: string
  option?: string | null
  isin?: string | null
  nav_date?: string
  // US
  industry?: string | null
  return_1y?: number | null
}

export interface ListingSource {
  source: string
  market: string
  count: number
  fetched_at: string | null
  stale: boolean
  error: string | null
}

export interface ListingPage {
  total: number
  offset: number
  limit: number
  rows: Listing[]
  facets: {
    sectors: Array<{ value: string; count: number }>
    categories: Array<{ value: string; count: number }>
    types: Partial<Record<ListingType, number>>
    shariah?: Partial<Record<ShariahStatus, number>>
    markets?: Record<string, number>
  }
  sources: ListingSource[]
}

export interface ListingQuery {
  market: string
  type?: string
  q?: string
  sector?: string
  plan?: string
  option?: string
  category?: string
  cap?: string
  shariah?: string
  sip_edge?: string
  price_min?: number
  price_max?: number
  change_min?: number
  change_max?: number
  near_high?: number
  near_low?: number
  min_volume?: number
  max_volume?: number
  min_cap?: number
  max_cap?: number
  markets?: string
  sort?: string
  order?: 'asc' | 'desc'
  offset?: number
  limit?: number
}

export async function getListings(params: ListingQuery, signal?: AbortSignal): Promise<ListingPage> {
  const res = await apiClient.get<ListingPage>('/listings', { params, signal })
  return res.data
}

export async function searchListings(
  q: string,
  market = 'all',
  type = 'all',
  limit = 10,
  signal?: AbortSignal,
): Promise<Listing[]> {
  const res = await apiClient.get<Listing[]>('/listings/search', { params: { q, market, type, limit }, signal })
  return res.data
}

export async function refreshListings(market: string): Promise<ListingSource[]> {
  const res = await apiClient.post<ListingSource[]>('/listings/refresh', null, { params: { market } })
  return res.data
}

export interface NavPoint {
  date: string
  nav: number
}

export async function getFundHistory(code: string, days = 3650): Promise<NavPoint[]> {
  const res = await apiClient.get<NavPoint[]>(`/listings/mf/${encodeURIComponent(code)}/history`, { params: { days } })
  return res.data
}

/** Market value the rest of the app (quote/history/analyze) expects. */
/** Where a row opens: Analyze, in its Mutual funds section for a fund. */
export function analyzeLink(row: Pick<Listing, 'symbol' | 'market'> & { type?: string }): string {
  if (row.type === 'mf') return `/analyze?view=funds&symbol=${encodeURIComponent(row.symbol)}&market=india`
  return `/analyze?symbol=${encodeURIComponent(row.symbol)}&market=${encodeURIComponent(row.market)}`
}

export interface MoverRow {
  symbol: string
  name: string | null
  price: number | null
  change_percent: number | null
  volume: number | null
  traded_value: number | null
  market_cap: number | null
  currency: string | null
  sector: string | null
  high_52w: number | null
  low_52w: number | null
}

export interface SectorMove {
  sector: string
  change_percent: number | null
  count: number
  advancers: number
  decliners: number
  leader: { symbol: string; change_percent: number } | null
  laggard: { symbol: string; change_percent: number } | null
  /** Largest stocks in the sector, biggest first. */
  members: Array<{ symbol: string; change_percent: number }>
}

/** How fresh a Market insights view's prices are (server live_market.py). */
export interface LiveInfo {
  /** Market in session (for ticker views: something traded in the last 15 min). */
  open: boolean
  /** Live prices are folded in (else the view runs on the last snapshot). */
  live: boolean
  /** Epoch seconds of the last price refresh / last trade. */
  updated: number | null
  age_seconds: number | null
  refresh_seconds: number
  /** How many names / tickers carry a live price. */
  covered: number
  source: string
  error: string | null
}

export interface Discovery {
  market: string
  as_of: string | null
  live?: LiveInfo | null
  universe: number
  indices: Array<{ market: string; name: string; price: number | null; change_percent: number | null }>
  breadth: { advancers: number; decliners: number; unchanged: number; total: number }
  gainers: MoverRow[]
  losers: MoverRow[]
  active: MoverRow[]
  near_high: MoverRow[]
  near_low: MoverRow[]
  sectors: SectorMove[]
}

export async function getDiscovery(market: string, size = 500, signal?: AbortSignal): Promise<Discovery> {
  const res = await apiClient.get<Discovery>('/listings/discovery', { params: { market, size }, signal })
  return res.data
}

export type Quadrant = 'leading' | 'weakening' | 'lagging' | 'improving'

interface RotationSector {
  sector: string
  members: string[]
  ratio: number
  momentum: number
  quadrant: Quadrant
  return_4w: number | null
  tail: Array<{ week: string; ratio: number; momentum: number }>
}

interface Rotation {
  market: string
  benchmark: { symbol: string; name: string }
  as_of: string
  window_weeks: number
  sectors: RotationSector[]
  live?: LiveInfo | null
}

export interface FundRotationItem {
  name: string
  code?: string
  symbol?: string
  amc?: string | null
  category?: string | null
  funds?: number
  total_funds?: number
  ratio: number
  momentum: number
  quadrant: Quadrant
  return_4w: number | null
  tail: { week: string; ratio: number; momentum: number }[]
}

export interface FundRotation {
  by: 'category' | 'amc' | 'view'
  group: string | null
  market?: string
  benchmark: { symbol: string; name: string }
  as_of: string
  window_weeks: number
  items: FundRotationItem[]
  groups: string[] | null
  live?: LiveInfo | null
}

export async function getFundRotation(by: 'category' | 'amc', group: string | null, signal?: AbortSignal): Promise<FundRotation> {
  const params: Record<string, string> = { by }
  if (group) params.group = group
  return (await apiClient.get<FundRotation>('/listings/fund-rotation', { params, signal, timeout: 150000 })).data
}

export async function getEtfRotation(market: string, view: string | null, signal?: AbortSignal): Promise<FundRotation> {
  const params: Record<string, string> = { market }
  if (view) params.view = view
  return (await apiClient.get<FundRotation>('/listings/etf-rotation', { params, signal, timeout: 120000 })).data
}

export async function getRotation(market: string, signal?: AbortSignal): Promise<Rotation> {
  return (await apiClient.get<Rotation>('/listings/rotation', { params: { market }, signal })).data
}

export interface SipRun {
  day: number
  installments: number
  invested: number
  units: number
  avg_cost: number
  value: number
  gain_pct: number
  xirr_pct: number | null
}

export interface SipResult {
  backtest: {
    error?: string
    start: string
    end: string
    monthly: number
    sip: SipRun
    lumpsum: { date: string; invested: number; value: number; gain_pct: number; cagr_pct: number | null }
    winner: 'sip' | 'lumpsum'
    by_day: SipRun[]
    day_spread: { best_day: number; worst_day: number; diff_pts: number } | null
    note: string | null
  }
  step_up: {
    monthly: number
    step_pct: number
    years: number
    expected_pct: number
    invested: number
    corpus: number
    flat_invested: number
    flat_corpus: number
    yearly: Array<{ year: number; monthly_sip: number; corpus: number; flat_corpus: number }>
  }
}

export interface SipParams {
  monthly: number
  years: number
  day: number
  step_up: number
  expected: number
  horizon: number
}

export async function getFundSip(code: string, params: SipParams): Promise<SipResult> {
  const res = await apiClient.get<SipResult>(`/listings/mf/${encodeURIComponent(code)}/sip`, { params })
  return res.data
}

export interface FundHolding {
  name: string
  isin: string | null
  symbol: string | null
  sector: string | null
  weight: number // percent of net assets
  hedged?: number | null // part held as an arbitrage (hedged) position
  kind: 'equity' | 'foreign_equity' | 'reit' | 'debt' | 'fund' | 'cash'
  value_lakh?: number | null
}

export interface FundHoldings {
  status: 'ok' | 'missing' | 'unknown'
  amc?: string
  scheme?: string
  as_of?: string | null
  source?: string
  note?: string | null
  weights?: 'reported' | 'estimated'
  count?: number
  aum_cr?: number | null
  holdings?: FundHolding[]
  top?: FundHolding[]
  top10_weight?: number
  /** effective number of equal-weight stocks (1 / sum of squared weights) and the largest weight */
  concentration?: { effective_stocks: number | null; top_weight: number; count: number } | null
  /** last month's trading from the change in shares held; turnover = lesser of buys and sells / fund size */
  churn?: { month_pct: number; yearly_pct: number; bought_cr: number; sold_cr: number } | null
  sectors?: { name: string; weight: number }[]
  mix?: { kind: FundHolding['kind']; weight: number }[]
  /** SEBI size buckets of the equity: top 100 by market cap = large, next 150 = mid. */
  cap_split?: { kind: 'large' | 'mid' | 'small' | 'foreign' | 'other'; weight: number }[] | null
  changes?: {
    since: string | null
    new: { name: string; symbol: string | null; weight: number }[]
    exited: { name: string; weight: number }[]
    moved: { name: string; symbol: string | null; from: number; to: number }[]
  } | null
}

// ---------------------------------------------------------------- fund competitors

export interface FundRank {
  rank: number
  of: number
  quartile: 1 | 2 | 3 | 4
  median: number
}

export interface FundPeerRow {
  code: string
  name: string
  amc: string | null
  is_self: boolean
  nav: number | null
  since: string | null
  r1: number | null
  r3: number | null
  r5: number | null
  volatility: number | null
  drawdown: number | null
  sharpe: number | null
  /** Correlation of daily returns with the chosen fund, last year. */
  similarity: number | null
  /** % of the portfolio held in common (both portfolio files loaded). */
  overlap: number | null
}

export interface FundPeers {
  status: 'ok' | 'unknown'
  code: string
  name: string
  category: string | null
  group: string | null
  plan: string | null
  count: number
  ranks: Partial<Record<'r1' | 'r3' | 'r5' | 'volatility' | 'drawdown' | 'sharpe', FundRank | null>>
  rows: FundPeerRow[]
  closest: Array<{ code: string; name: string; similarity: number }>
  risk_free: number
  note: string
}

export async function getFundPeers(code: string, signal?: AbortSignal): Promise<FundPeers> {
  return (await apiClient.get<FundPeers>(`/listings/mf/${encodeURIComponent(code)}/peers`, { signal, timeout: 120000 })).data
}

export async function getFundHoldings(code: string, signal?: AbortSignal): Promise<FundHoldings> {
  return (await apiClient.get<FundHoldings>(`/listings/mf/${encodeURIComponent(code)}/holdings`, { signal, timeout: 60000 })).data
}

export interface FundsHolding {
  symbol: string
  isin?: string
  count?: number
  houses_loaded?: number
  note?: string
  funds: { amc: string; scheme: string; weight: number; prev_weight: number | null; value_cr: number | null; as_of: string | null }[]
}

export async function getFundsHolding(symbol: string, signal?: AbortSignal): Promise<FundsHolding> {
  return (await apiClient.get<FundsHolding>(`/listings/stock/${encodeURIComponent(symbol)}/funds`, { signal })).data
}

export interface SipWindow {
  best: number
  worst: number
  best_xirr: number
  spread: number
}

export interface SipDays {
  summary: {
    as_of: string
    best_day: number
    spread: number
    edge: SipEdge
    windows: Record<string, SipWindow>
  } | null
  curve: Array<{ day: number; xirr_pct: number | null }>
  years: number
  note?: string
}

/** Best SIP day for one Indian fund (kind "mf") or ETF (India, US, Hong Kong). */
export async function getSipDays(market: string, kind: 'mf' | 'etf', symbol: string, years = 10): Promise<SipDays> {
  const res = await apiClient.get<SipDays>(`/listings/${market}/${kind}/${encodeURIComponent(symbol)}/sip-days`, {
    params: { years },
    timeout: 60_000,
  })
  return res.data
}

export interface BigTrade {
  date: string
  kind: string
  symbol: string
  name: string | null
  name_local?: string | null
  client: string | null
  side: string
  qty: number | null
  price: number | null
  value: number | null
  remarks: string | null
}

export interface WhalePosition {
  coin: string
  top_long_pct: number
  top_ratio: number | null
  top_ratio_change: number
  open_interest: number | null
  oi_change_1d: number | null
  oi_change_7d: number | null
  taker_ratio: number | null
}

export interface BigTrades {
  market: string
  days: number
  as_of: string
  title: string
  subtitle: string
  currency: string
  note: string
  deals?: BigTrade[]
  positions?: WhalePosition[]
}

export async function getBigTrades(market: string, days = 1, signal?: AbortSignal): Promise<BigTrades> {
  return (await apiClient.get<BigTrades>('/listings/big-trades', { params: { market, days }, signal, timeout: 150000 })).data
}

// ---------------------------------------------------------------- hot stocks

export interface HotRow {
  symbol: string
  name: string | null
  market: string
  price: number | null
  change_percent: number | null
  market_cap: number | null
  currency: string | null
  sector: string | null
  /** Plain reason it is on the board (facts, never a call). */
  why: string
  from_high?: number | null
  from_low?: number | null
  activity?: number | null
}

export interface HotBoard {
  key: string
  title: string
  description: string
  rows: HotRow[]
  /** Why a board is empty in this market (e.g. no 52-week range). */
  note: string | null
}

interface HotStocks {
  market: string
  area: 'trader' | 'investor'
  as_of: string | null
  universe: string
  boards: HotBoard[]
  live?: LiveInfo | null
}

export async function getHotStocks(market: string, area: 'trader' | 'investor', signal?: AbortSignal): Promise<HotStocks> {
  return (await apiClient.get<HotStocks>('/listings/hot', { params: { market, area }, signal, timeout: 120_000 })).data
}

export interface RollingWindow {
  years: number
  windows: number
  from: string
  median: number
  mean: number
  min: number
  max: number
  worst_start: string
  best_start: string
  negative_pct: number
  above_8_pct: number
  above_12_pct: number
  bench_median: number | null
  /** share of the same windows where the fund beat its benchmark */
  beat_pct: number | null
  compared: number
}

export interface FundRisk {
  years: number
  from: string
  risk_free: number
  /** fractions (0.12 = 12%) */
  annual_return: number
  volatility: number
  sharpe: number | null
  sortino: number | null
  max_drawdown: number
  beta: number | null
  alpha: number | null
  correlation: number | null
  tracking_error?: number
  information_ratio?: number | null
  up_capture?: number | null
  down_capture?: number | null
  bench_annual_return: number | null
  bench_volatility: number | null
  bench_max_drawdown: number | null
}

export interface DrawdownEpisode {
  peak: string
  trough: string
  recovered: string | null
  depth: number
  days_down: number
  days_to_recover: number | null
}

export interface FundAnalytics {
  status: 'ok' | 'no_history'
  note: string
  category?: string | null
  nav_from?: string
  benchmark?: { symbol: string; name: string; available: boolean; dividend_yield: number | null } | null
  payout_option?: boolean
  rolling?: { windows: RollingWindow[]; chart_years: number | null; chart: { date: string; fund: number; bench: number | null }[] }
  risk?: FundRisk | null
  drawdowns?: {
    current: number
    max: number
    episodes: DrawdownEpisode[]
    crashes: { label: string; from: string; to: string; fund: number; bench: number | null }[]
    chart: { date: string; fund: number; bench: number | null }[]
  }
}

export async function getFundAnalytics(code: string, signal?: AbortSignal): Promise<FundAnalytics> {
  return (await apiClient.get<FundAnalytics>(`/listings/mf/${encodeURIComponent(code)}/analytics`, { signal, timeout: 120000 })).data
}

export interface FundOverlap {
  status: 'ok' | 'missing'
  a: { scheme: string | null; as_of: string | null }
  b: { scheme: string | null; as_of: string | null }
  /** % of the money in the same stocks: sum over shared stocks of the smaller weight */
  overlap?: number
  shared_count?: number
  only_a?: number
  only_b?: number
  shared?: { name: string; symbol: string | null; weight_a: number; weight_b: number }[]
  note: string | null
}

export async function getFundOverlap(code: string, other: string, signal?: AbortSignal): Promise<FundOverlap> {
  return (await apiClient.get<FundOverlap>(`/listings/mf/${encodeURIComponent(code)}/overlap`, { params: { other }, signal, timeout: 90_000 })).data
}

export interface FundTaxRules {
  label: string
  short_months: number | null
  short_rate: number | null
  long_rate: number | null
  exemption: number
  short_slab: boolean
  long_slab: boolean
  text: string
  cess: number
  rules_from: string
}

export interface FundCost {
  status: 'ok' | 'unknown'
  plan?: string
  tax_class?: 'equity' | 'debt' | 'other'
  tax?: FundTaxRules
  plans?: { years: number; direct: number; regular: number; gap: number; from: string; to: string; direct_name: string; regular_name: string; direct_code: string; regular_code: string } | null
  cost?: { years: number; lumpsum: number; sip: number; lumpsum_direct: number; lumpsum_regular: number; sip_direct: number; sip_regular: number; assumed_return: number } | null
  note?: string
}

export async function getFundCost(code: string, signal?: AbortSignal): Promise<FundCost> {
  return (await apiClient.get<FundCost>(`/listings/mf/${encodeURIComponent(code)}/cost`, { signal, timeout: 90_000 })).data
}

export interface FundStyle {
  status: 'ok' | 'missing'
  note?: string | null
  category?: string | null
  size?: 'Large' | 'Mid' | 'Small' | 'Multi' | null
  style?: { label: 'Value' | 'Blend' | 'Growth'; score: number } | null
  fund?: { pe: number | null; pb: number | null; roe: number | null; pe_coverage: number }
  market?: { pe: number | null; pb: number | null; roe: number | null }
  equity_pct?: number
  count?: number
  checks?: { rule: string; ok: boolean }[]
  as_of?: string | null
}

export async function getFundStyle(code: string, signal?: AbortSignal): Promise<FundStyle> {
  return (await apiClient.get<FundStyle>(`/listings/mf/${encodeURIComponent(code)}/style`, { signal, timeout: 120_000 })).data
}

export interface FundAiReview {
  summary: string
  strengths: string[]
  concerns: string[]
  sections: Partial<Record<'returns' | 'risk' | 'portfolio' | 'peers' | 'cost', string>>
  view: 'strong' | 'fair' | 'weak' | null // owner only
  suits: string | null // owner only
  name: string | null
  category: string | null
  generated_at: string
  compliance: 'analytics'
}

export async function getFundAiReview(code: string, refresh = false): Promise<FundAiReview> {
  return (await apiClient.post<FundAiReview>(`/listings/mf/${encodeURIComponent(code)}/ai-review`, null, { params: { refresh }, timeout: 200_000 })).data
}

export interface BookLevel {
  price: number
  quantity: number
  orders: number | null
}

export interface TradingActivity {
  symbol: string
  market: string
  open: boolean
  age_seconds: number | null
  refresh_seconds: number
  source: string
  error: string | null
  quote: {
    price: number
    volume: number | null
    time?: number
    /** Broker feed only (India): shares waiting to be bought / sold. */
    buy_qty?: number
    sell_qty?: number
    avg_price?: number
    last_qty?: number
    upper_circuit?: number
    lower_circuit?: number
    depth?: { buy: BookLevel[]; sell: BookLevel[] }
  } | null
  /** India: last session's delivery figures from the exchange. */
  delivery?: { date: string | null; loading: boolean; percent?: number | null; delivered?: number | null; traded?: number | null }
}

export async function getTradingActivity(symbol: string, market: string, signal?: AbortSignal): Promise<TradingActivity> {
  return (await apiClient.get<TradingActivity>('/listings/activity', { params: { symbol, market }, signal })).data
}
