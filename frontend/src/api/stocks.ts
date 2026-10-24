import { saveBlob } from '../lib/files'
import { apiClient } from './client'

export interface Quote {
  symbol: string
  price: number
  previous_close?: number
  open?: number
  day_high?: number
  day_low?: number
  volume?: number
  market_cap?: number
  change?: number
  change_percent?: number
  [key: string]: unknown
}

export type HistoryRow = Record<string, number | string>

export async function getQuote(symbol: string, market = 'us'): Promise<Quote> {
  const res = await apiClient.get<Quote>(`/stocks/${encodeURIComponent(symbol)}/quote`, {
    params: { market },
  })
  return res.data
}

export async function getHistory(
  symbol: string,
  market = 'us',
  period = '1y',
  interval = '1d',
): Promise<HistoryRow[]> {
  const res = await apiClient.get<HistoryRow[]>(`/stocks/${encodeURIComponent(symbol)}/history`, {
    params: { market, period, interval },
  })
  return res.data
}

type Section<T> = T & { error?: string }

export interface OverviewIndicator {
  key: string
  name: string
  value: number | null
  /** null on public deploys (values only, no per-stock verdict) */
  signal: string | null
  note: string
}

export interface OverviewItem {
  label: string
  value: number | null
  kind: 'money' | 'ratio' | 'pct'
}

export interface StockOverview {
  symbol: string
  market: string
  technical: Section<{
    /** Absent on public deploys (no per-stock verdict). */
    overall?: string
    counts?: { buy: number; sell: number; neutral: number }
    indicators: OverviewIndicator[]
    /** Candlestick patterns and divergences on the latest bar */
    patterns?: Array<{ key: string; name: string; bias: 'bullish' | 'bearish' | 'neutral' | null }>
    averages: Array<{ period: number; value: number; above: boolean; distance_pct: number }>
    trend: string
    returns: Record<string, number | null>
    high_52w: number
    low_52w: number
    from_high_pct: number
    as_of: string
  }>
  risk: Section<{
    level: string
    volatility_pct: number
    max_drawdown_pct: number
    beta: number | null
    worst_day_pct: number
    best_day_pct: number
    /** Realized-volatility estimators and cones (fractions, 0.2 = 20%) */
    realized?: {
      window: number
      estimators: Array<{ key: string; name: string; value: number | null }>
      cones: Array<{ window: number; current: number; min: number; p25: number; median: number; p75: number; max: number; percentile: number }>
      regime: 'calm' | 'normal' | 'stormy' | null
      percentile: number | null
      /** GARCH(1,1) forecast, annualised fractions */
      garch?: {
        current: number
        next_day: number
        long_run: number
        forecasts: Array<{ days: number; volatility: number }>
        persistence: number
        half_life_days: number | null
      } | null
    } | null
  }>
  fundamentals: Section<{
    score: number
    valuation_status: string | null
    health_rating: string | null
    currency: string | null
    groups: Array<{ title: string; items: OverviewItem[] }>
  }>
  analysts: Section<{
    recommendation: string | null
    mean_score: number | null
    count: number | null
  }>
  events: Section<{
    earnings_date: string | null
    ex_dividend_date: string | null
    dividend_date: string | null
    eps_estimate: number | null
    revenue_estimate: number | null
  }>
  profile: Section<{
    name: string | null
    sector: string | null
    industry: string | null
    country: string | null
    employees: number | null
    website: string | null
    summary: string | null
    exchange: string | null
    currency: string | null
  }>
  news: Section<{
    items?: Array<{ title: string; source: string; url: string; published: string | null; snippet?: string }>
  }>
}

export async function getOverview(symbol: string, market = 'us'): Promise<StockOverview> {
  const res = await apiClient.get<StockOverview>(`/stocks/${encodeURIComponent(symbol)}/overview`, {
    params: { market },
  })
  return res.data
}

export type FinancialPeriod = 'annual' | 'quarterly'
export type FindingTone = 'good' | 'bad' | 'neutral' | 'info'

export interface StatementRow {
  key: string
  label: string
  kind: 'money' | 'number'
  values: Array<number | null>
}

export interface Verdict {
  score: number | null
  label: 'strong' | 'mixed' | 'weak' | 'n/a'
  good: number
  bad: number
  neutral: number
}

export interface Statement {
  as_of: string | null
  rows: StatementRow[]
  metrics: Record<string, number | string | null | Record<string, Array<number | null>>>
  findings: Array<{ tone: FindingTone; text: string }>
  verdict: Verdict
}

export interface QualityScores {
  financial_sector: boolean
  note?: string
  piotroski: null | {
    score: number
    out_of: number
    label: 'strong' | 'average' | 'weak'
    tests: Array<{ key: string; label: string; pass: boolean | null; detail: string }>
  }
  altman: null | {
    score: number
    model: string
    zone: 'safe' | 'grey' | 'distress'
    safe_above: number
    distress_below: number
    parts: Record<string, number | null>
  }
  beneish: null | {
    score: number
    flag: boolean
    threshold: number
    ratios: Record<string, number | null>
    neutral: string[]
  }
}

export interface Financials {
  symbol: string
  market: string
  name: string
  period: FinancialPeriod
  currency: string | null
  sector: string | null
  financial_sector: boolean
  periods: string[]
  income: Statement
  balance: Statement
  cashflow: Statement
  overall: Verdict
  summary: string
  source: string
  quality?: QualityScores | null
}

export async function getFinancials(symbol: string, market = 'us', period: FinancialPeriod = 'annual'): Promise<Financials> {
  const res = await apiClient.get<Financials>(`/stocks/${encodeURIComponent(symbol)}/financials`, {
    params: { market, period },
  })
  return res.data
}

export async function getFinancialsAiSummary(symbol: string, market = 'us', period: FinancialPeriod = 'annual'): Promise<string> {
  const res = await apiClient.post<{ summary: string }>(
    `/stocks/${encodeURIComponent(symbol)}/financials/ai-summary`,
    null,
    { params: { market, period }, timeout: 150_000 },
  )
  return res.data.summary
}

export interface Officer {
  name: string
  title: string | null
  age: number | null
  year_born: number | null
  total_pay: number | null
  fiscal_year: number | null
}

export interface Leadership {
  symbol: string
  market: string
  name: string | null
  currency: string | null
  ceo: Officer | null
  officers: Officer[]
  governance: Array<{ key: string; label: string; score: number }>
  governance_as_of: string | null
}

export type CeoVerdict = 'strong' | 'steady' | 'uncertain' | 'concerning'

export interface CeoBrief {
  symbol: string
  ceo: string
  introduction: string
  achievements: string[]
  pitfalls: string[]
  verdict: CeoVerdict
  verdict_reason: string
}

export async function getLeadership(symbol: string, market = 'us'): Promise<Leadership> {
  const res = await apiClient.get<Leadership>(`/stocks/${encodeURIComponent(symbol)}/leadership`, { params: { market } })
  return res.data
}

export async function getCeoBrief(symbol: string, market = 'us'): Promise<CeoBrief> {
  const res = await apiClient.post<CeoBrief>(`/stocks/${encodeURIComponent(symbol)}/leadership/ai-brief`, null, {
    params: { market },
    timeout: 150_000,
  })
  return res.data
}

export type ShariahVerdict = 'halal' | 'doubtful' | 'haram' | 'unknown'

export interface ShariahCheck {
  key: 'debt' | 'cash' | 'receivables' | 'interest_income'
  label: string
  /** Percent of `basis`, or null when Yahoo has no figure. */
  value: number | null
  limit: number
  /** AAOIFI's stricter limit, where it differs. */
  strict_limit: number | null
  basis: string
  status: 'pass' | 'fail' | 'borderline' | 'unknown'
  note?: string
}

export interface ShariahProfile {
  symbol: string
  market: string
  name: string
  sector: string | null
  industry: string | null
  currency: string | null
  kind: 'stock' | 'fund'
  verdict: ShariahVerdict
  verdict_label: string
  business: { status: ShariahVerdict; reason: string; flags: string[] }
  checks: ShariahCheck[]
  market_cap_basis?: string | null
  period?: string | null
  /** Interest income as % of revenue - the share of dividends to give away. */
  purification_pct: number | null
  reasons: string[]
  source: string
}

export async function getShariah(symbol: string, market = 'us'): Promise<ShariahProfile> {
  const res = await apiClient.get<ShariahProfile>(`/stocks/${encodeURIComponent(symbol)}/shariah`, {
    params: { market },
    timeout: 90_000,
  })
  return res.data
}

export interface Holder {
  holder: string
  pct_held: number | null
  shares: number | null
  value: number | null
  pct_change: number | null
  reported: string | null
}

export interface Ownership {
  symbol: string
  market: string
  breakdown: { insiders_pct: number | null; institutions_pct: number | null; float_shares: number | null; shares_outstanding: number | null }
  institutions: Holder[]
  funds: Holder[]
  insiders: {
    days: number
    buys: number
    sells: number
    buy_value: number
    sell_value: number
    bias: 'net buying' | 'net selling' | null
    recent: Array<{ date: string; insider: string; position: string; side: 'buy' | 'sell' | 'other'; shares: number | null; value: number | null; text: string }>
  }
  short: { shares: number; prior_month: number | null; change_pct: number | null; pct_of_float: number | null; days_to_cover: number | null; as_of: string | null } | null
  /** NSE bulk / block deals (India only) */
  deals?: DealsResponse | null
}

export interface Deal {
  date: string
  kind: 'bulk' | 'block'
  symbol: string
  name: string | null
  client: string | null
  side: string
  qty: number | null
  price: number | null
  value: number | null
  remarks: string | null
}

export interface DealsResponse {
  days: number
  history_from: string | null
  latest: string | null
  count: number
  deals: Deal[]
}

export async function getDeals(days = 1): Promise<DealsResponse> {
  return (await apiClient.get<DealsResponse>('/listings/deals', { params: { days } })).data
}

export async function getOwnership(symbol: string, market = 'us'): Promise<Ownership> {
  return (await apiClient.get<Ownership>(`/stocks/${encodeURIComponent(symbol)}/ownership`, { params: { market } })).data
}

export interface MdnaSummary {
  symbol: string
  form: '10-K' | '10-Q'
  filed: string
  period: string
  url: string
  chars: number
  summary: string
}

export async function getMdnaSummary(symbol: string): Promise<MdnaSummary> {
  const res = await apiClient.post<MdnaSummary>(`/stocks/${encodeURIComponent(symbol)}/mdna/ai-summary`, null, {
    params: { market: 'us' },
    timeout: 150000,
  })
  return res.data
}

export interface Dcf {
  symbol: string
  market: string
  name: string
  currency: string | null
  price: number | null
  periods: string[]
  note: string | null
  source: string
  graham: null | { value: number; eps: number; book_value_per_share: number; vs_price_pct: number | null }
  dcf: null | {
    base_fcf: number
    base_label: string
    net_cash: number
    /** Stock-based compensation taken off the latest year's cash flow (null: not reported). */
    sbc: number | null
    /** Long-term investments counted with cash. */
    long_term_investments: number
    shares: number
    fcf_history: Array<number | null>
    converted_from: string | null
    defaults: { growth: number; discount: number; terminal: number; high_years: number; total_years: number }
    value: number | null
    vs_price_pct: number | null
    implied_growth: number | null
  }
}

export async function getDcf(symbol: string, market = 'us'): Promise<Dcf> {
  const res = await apiClient.get<Dcf>(`/stocks/${encodeURIComponent(symbol)}/dcf`, { params: { market } })
  return res.data
}

/** The DCF as an Excel workbook with live formulas, at the given rates (fractions). */
export async function downloadDcfModel(symbol: string, market: string, rates: { growth: number; discount: number; terminal: number }): Promise<void> {
  const res = await apiClient.get(`/stocks/${encodeURIComponent(symbol)}/dcf/model.xlsx`, {
    params: { market, ...rates },
    responseType: 'blob',
    timeout: 120_000,
  })
  saveBlob(res.data as Blob, `${symbol}-dcf-model.xlsx`)
}

export interface ChecklistRule {
  key: string
  label: string
  pass: boolean | null
  value: string
  why: string
}

export interface Checklists {
  symbol: string
  market: string
  name: string
  financial_sector: boolean
  source: string
  lenses: Array<{ key: string; name: string; source: string; rules: ChecklistRule[]; passed: number; tested: number; total: number; note: string | null }>
}

export async function getChecklists(symbol: string, market = 'us'): Promise<Checklists> {
  const res = await apiClient.get<Checklists>(`/stocks/${encodeURIComponent(symbol)}/checklists`, { params: { market } })
  return res.data
}
