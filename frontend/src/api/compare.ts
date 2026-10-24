import { apiClient } from './client'

export interface CompareItem {
  symbol: string
  market: string
  yahoo: string
  name: string
  currency: string | null
  sector: string | null
  industry: string | null
  price: number | null
}

export interface CompareMetric {
  label: string
  kind: 'money' | 'ratio' | 'pct' | 'count'
  group: string
  values: Record<string, number | null>
  best: string | null
  higher_better: boolean | null
}

export interface CompareResult {
  period: string
  items: CompareItem[]
  chart: Array<{ time: string } & Record<string, number>>
  returns: Array<{ window: string; values: Record<string, number | null> }>
  risk: Record<string, { volatility: number; max_drawdown: number; beta: number | null; benchmark: string; return_period: number; sharpe_like: number | null }>
  correlation: { symbols: string[]; matrix: (number | null)[][] } | null
  metrics: CompareMetric[]
  warnings: string[]
}

export interface PeerResult {
  symbol: string
  market: string
  basis: string | null
  industry?: string | null
  note?: string
  peers: Array<{ symbol: string; name: string | null; market_cap: number; industry: string | null; price: number | null; change_percent: number | null; pe: number | null; currency: string | null }>
}

export async function compareStocks(items: Array<{ symbol: string; market: string }>, period: string): Promise<CompareResult> {
  const s = items.map((i) => `${i.symbol}:${i.market}`).join(',')
  return (await apiClient.get<CompareResult>('/compare', { params: { s, period }, timeout: 90_000 })).data
}

export async function getPeers(symbol: string, market: string): Promise<PeerResult> {
  return (await apiClient.get<PeerResult>(`/stocks/${encodeURIComponent(symbol)}/peers`, { params: { market }, timeout: 90_000 })).data
}

/** /compare?s=AAPL:us,MSFT:us link */
export function compareLink(items: Array<{ symbol: string; market: string }>): string {
  return `/compare?s=${encodeURIComponent(items.map((i) => `${i.symbol}:${i.market}`).join(','))}`
}

export interface EstimatePeriod {
  key: string
  label: string
  eps: { avg: number | null; low: number | null; high: number | null; year_ago: number | null; growth: number | null; analysts: number | null }
  revenue: { avg: number | null; low: number | null; high: number | null; year_ago: number | null; growth: number | null; analysts: number | null }
  trend: { current: number | null; d7: number | null; d30: number | null; d60: number | null; d90: number | null; change_30d: number | null; change_90d: number | null }
  revisions: { up_7d: number | null; up_30d: number | null; down_7d: number | null; down_30d: number | null }
}

export interface Estimates {
  currency: string | null
  periods: EstimatePeriod[]
  history: Array<{ quarter: string; actual: number | null; estimate: number | null; surprise: number | null }>
  momentum: { change_90d: number; label: 'rising' | 'falling' | 'steady' } | null
  beats: { beat: number; total: number } | null
  available: boolean
}

export async function getEstimates(symbol: string, market: string): Promise<Estimates> {
  return (await apiClient.get<Estimates>(`/stocks/${encodeURIComponent(symbol)}/estimates`, { params: { market }, timeout: 60_000 })).data
}

export interface EtfLookthrough {
  symbol: string
  market: string
  is_etf: boolean
  status?: 'ok' | 'no_stocks' | 'unsupported' | 'unknown'
  name?: string | null
  index?: string
  category?: string | null
  family?: string | null
  expense_ratio?: number | null
  category_expense_ratio?: number | null
  total_assets?: number | null
  count?: number | null
  weights?: 'estimated' | 'reported'
  top?: Array<{ symbol: string; name: string; weight: number; sector?: string }>
  top10_weight?: number
  sectors?: Array<{ name: string; weight: number }>
  assets?: Record<string, number>
  source?: string
  note?: string
}

export interface EtfOverlap {
  available: boolean
  a: string
  b: string
  overlap?: number
  shared_count?: number
  shared?: Array<{ symbol: string; weight_a: number; weight_b: number }>
  partial?: boolean
  note?: string | null
}

export async function getEtf(symbol: string, market: string): Promise<EtfLookthrough> {
  return (await apiClient.get<EtfLookthrough>(`/etf/${encodeURIComponent(symbol)}`, { params: { market }, timeout: 60_000 })).data
}

export async function getEtfOverlap(a: { symbol: string; market: string }, b: { symbol: string; market: string }): Promise<EtfOverlap> {
  return (await apiClient.get<EtfOverlap>('/etf-overlap', { params: { a: a.symbol, b: b.symbol, market_a: a.market, market_b: b.market }, timeout: 90_000 })).data
}

export interface Dividends {
  pays: boolean
  currency: string | null
  ttm?: number
  ttm_yield?: number | null
  forward_rate?: number | null
  forward_yield?: number | null
  five_year_avg_yield?: number | null
  payout_ratio?: number | null
  growth_5y?: number | null
  years_without_cut?: number
  frequency?: string | null
  last?: { date: string; amount: number }
  next_ex_date?: string | null
  years?: Array<{ year: number; total: number; partial: boolean }>
  payments?: Array<{ date: string; amount: number }>
  first_year?: number
}

export async function getDividends(symbol: string, market: string): Promise<Dividends> {
  return (await apiClient.get<Dividends>(`/stocks/${encodeURIComponent(symbol)}/dividends`, { params: { market }, timeout: 60_000 })).data
}

export interface ValuationMultiple {
  key: 'pe' | 'pb' | 'ps'
  label: string
  value: number | null
  sector_median: number | null
  ratio: number | null
}

export interface Valuation {
  status: 'ok' | 'unavailable'
  reason?: string | null
  sector?: string | null
  peers?: number
  universe?: string
  price?: number | null
  currency?: string | null
  multiples?: ValuationMultiple[]
  position?: number | null
  zone?: 'below' | 'in_line' | 'above' | null
  bands?: { below: number; above: number }
  garp?: {
    peg: number | null
    earnings_growth: number | null
    revenue_growth: number | null
    rules: { rule: string; field: string; value: number | null; pass: boolean | null }[]
    passed: number
    total: number
    missing?: number
  }
}

/** Valuation meter: the stock's multiples against its sector median (src/services/valuation.py). */
export async function getValuation(symbol: string, market: string): Promise<Valuation> {
  return (await apiClient.get<Valuation>(`/stocks/${encodeURIComponent(symbol)}/valuation`, { params: { market }, timeout: 100_000 })).data
}

export interface EarningsEvent {
  date: string
  at: string
  estimate: number | null
  actual: number | null
  surprise: number | null
  reaction: { move: number; from: string; to: string } | null
  /** a surprise so large it is more likely a data mix-up than a real miss / beat */
  unusual: boolean
}

export interface Earnings {
  available: boolean
  symbol: string
  market: string
  currency: string | null
  sector: string | null
  next: EarningsEvent | null
  days_to_next: number | null
  implied: { move: number; expiry: string; strike: number } | null
  latest: EarningsEvent | null
  history: EarningsEvent[]
  stats: {
    reports: number
    avg_abs_move: number
    biggest_up: number
    biggest_down: number
    up_days: number
    beats: number
    misses: number
    avg_move_on_beat: number | null
    avg_move_on_miss: number | null
  } | null
  consensus: { period: string; eps: { avg: number | null; analysts: number | null }; trend: { change_90d: number | null } } | null
  watch: string[]
  source: string
}

export async function getEarnings(symbol: string, market: string): Promise<Earnings> {
  return (await apiClient.get<Earnings>(`/stocks/${encodeURIComponent(symbol)}/earnings`, { params: { market }, timeout: 90000 })).data
}
