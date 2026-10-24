import { apiClient } from './client'
import type { LiveInfo } from './listings'

export interface MacroSeries {
  id: string
  label: string
  group: 'us' | 'india' | 'global'
  unit: string
  note: string
  value: number
  date: string
  change_1m: number | null
  change_1y: number | null
  spark: Array<{ date: string; value: number }>
}

export interface MacroData {
  series: MacroSeries[]
  failed: string[]
  signals: { us_curve_inverted: boolean | null }
  source: string
}

export async function getMacro(signal?: AbortSignal): Promise<MacroData> {
  return (await apiClient.get<MacroData>('/macro', { signal })).data
}

export interface Commodity {
  key: string
  label: string
  group: 'metals' | 'energy' | 'agri' | 'india'
  unit: string
  note: string
  price: number
  as_of: string
  change_1d: number | null
  change_1m: number | null
  change_1y: number | null
  spark: number[]
}

export async function getCommodities(
  signal?: AbortSignal,
): Promise<{ items: Commodity[]; usd_inr: number | null; live?: LiveInfo | null }> {
  return (await apiClient.get('/macro/commodities', { signal })).data
}

export interface CotItem {
  key: string
  label: string
  as_of: string
  open_interest: number
  managed_money_long: number
  managed_money_short: number
  managed_money_net: number
  net_change_1w: number | null
  net_pct_oi: number | null
  producer_net: number
  index_3y: number | null
  reading: string
  history: number[]
}

export async function getCot(signal?: AbortSignal): Promise<{ items: CotItem[]; as_of: string | null; source: string }> {
  return (await apiClient.get('/macro/cot', { signal })).data
}

export interface EiaItem {
  key: string
  label: string
  unit: 'mb' | '%'
  note: string
  week_ending: string
  value: number
  change_1w: number
  avg_5y: number | null
  vs_avg_5y: number | null
  spark: number[]
}

export async function getEia(signal?: AbortSignal): Promise<{ items: EiaItem[]; week_ending: string | null; source: string }> {
  return (await apiClient.get('/macro/eia', { signal })).data
}

export interface YieldCurve {
  points: Array<{ id: string; tenor: string; years: number; now: number | null; month_ago: number | null; year_ago: number | null }>
  as_of: string | null
  shape?: { spread_10y_3m: number; label: 'inverted' | 'flat' | 'normal' } | null
  source?: string
}

export async function getYieldCurve(signal?: AbortSignal): Promise<YieldCurve> {
  return (await apiClient.get<YieldCurve>('/macro/yield-curve', { signal })).data
}

export interface IndiaRates {
  rbi: {
    policy?: Array<{ key: string; label: string; value: number | null; note: string }>
    tbills?: Array<{ days: number; years: number; yield: number | null }>
    gsecs?: Array<{ name: string; coupon: number; maturity_year: number; yield: number | null }>
    fx?: Array<{ pair: string; per: number; value: number | null }>
    lending?: Array<{ label: string; value: string }>
    call_rate?: { low: number; high: number } | null
    curve?: Array<{ label: string; years: number; yield: number }>
    fx_as_of?: string
    gsec_as_of?: string
    fetched_at?: string
    stale: boolean
    error?: string
  }
  ibja: {
    items?: Array<{ key: string; label: string; unit: string; am: number | null; pm: number | null; latest: number; session: 'AM' | 'PM'; change_pct: number | null }>
    as_of?: string
    history?: Record<string, Array<{ date: string; value: number }>>
    fetched_at?: string
    stale: boolean
    error?: string
  }
}

export async function getIndiaRates(signal?: AbortSignal): Promise<IndiaRates> {
  return (await apiClient.get<IndiaRates>('/macro/india', { signal, timeout: 60_000 })).data
}

export interface CrudeStock {
  symbol: string
  name: string
  weeks: number
  beta_market: number
  beta_crude: number
  t_crude: number
  significant: boolean
  corr_crude: number
  r2: number | null
  r2_added: number | null
  change_1m: number | null
  crude_implied_1m: number | null
}

export interface CrudeSensitivity {
  groups: Array<{ name: string; why: string; avg_beta_crude: number; stocks: CrudeStock[] }>
  market?: string
  crude_label?: string
  currency?: string
  index_name?: string
  crude?: number
  crude_change_1m?: number | null
  crude_change_1y?: number | null
  method?: string
  error?: string
}

export async function getCrudeSensitivity(market = 'india', signal?: AbortSignal): Promise<CrudeSensitivity> {
  return (await apiClient.get<CrudeSensitivity>('/macro/crude-sensitivity', { params: { market }, signal, timeout: 90_000 })).data
}

export interface RateItem {
  label: string
  value: number
  unit: string
  note: string
  change_1m: number | null
  change_1y: number | null
  change_kind: 'points' | 'pct'
  as_of: string
  spark: number[]
  tone?: 'up' | 'down'
}

export interface MarketRates {
  market: string
  title?: string
  sections: Array<{ title: string; note: string; source: string; items: RateItem[] }>
  errors: string[]
}

export async function getMarketRates(market: string, signal?: AbortSignal): Promise<MarketRates> {
  return (await apiClient.get<MarketRates>('/macro/rates', { params: { market }, signal, timeout: 90_000 })).data
}

export interface WorldItem {
  key: string
  label: string
  group: 'americas' | 'europe' | 'asia' | 'fx' | 'yields' | 'volatility'
  note: string
  price: number
  as_of: string
  change_unit: '%' | 'points'
  change_1d: number | null
  change_1m: number | null
  change_1y: number | null
  spark: number[]
}

export interface WorldMarkets {
  items: WorldItem[]
  failed: string[]
  vix_term: { vix: number; vix3m: number; ratio: number; shape: 'contango' | 'backwardation'; note: string } | null
  crypto_mood: {
    value: number
    label: string
    date: string
    week_ago: number | null
    month_ago: number | null
    spark: number[]
    source: string
  } | null
  source: string
  live?: LiveInfo | null
}

export async function getWorldMarkets(signal?: AbortSignal): Promise<WorldMarkets> {
  return (await apiClient.get<WorldMarkets>('/macro/world', { signal })).data
}

export interface ValuationSeries {
  key: string
  label: string
  note: string
  value: number
  date: string
  estimated: boolean
  stale: boolean
  percentile_all: number | null
  percentile_1990: number | null
  median_all: number | null
  median_1990: number | null
  since: string
  spark: Array<{ date: string; value: number }>
}

export interface IndexValuation {
  index: string
  date: string
  last: number | null
  history_from: string
  history_days: number
  pe: number | null
  pb: number | null
  dy: number | null
  pe_percentile: number | null
  pb_percentile: number | null
  dy_percentile: number | null
  pe_year_ago: number | null
}

export interface MarketValuation {
  us: { series: ValuationSeries[]; failed: string[]; source: string }
  india: { indices: IndexValuation[]; stale: boolean; as_of?: string; source: string }
}

export async function getMarketValuation(signal?: AbortSignal): Promise<MarketValuation> {
  return (await apiClient.get<MarketValuation>('/macro/valuation', { signal })).data
}

export interface CountryRow {
  code: string
  name: string
  fiscal_year: string | null
  [indicator: string]: unknown
}

export interface CountryMacro {
  years: number[]
  projection_from: number
  indicators: Array<{ key: string; label: string; unit: string; note: string }>
  rows: CountryRow[]
  countries: Array<{ code: string; name: string }>
  stale: boolean
  as_of: string
  source: string
}

export async function getCountryMacro(codes: string[], signal?: AbortSignal): Promise<CountryMacro> {
  return (await apiClient.get<CountryMacro>('/macro/countries', { params: { codes: codes.join(',') }, signal })).data
}

export interface PolicyRate {
  area: string
  name: string
  bank: string
  rate: number
  as_of: string
  last_change: string | null
  changed_between?: [string, string]
  previous: number | null
  direction: 'cut' | 'hike' | null
  change_1y: number | null
  inflation: number | null
  real_rate: number | null
  spark: Array<{ month: string; rate: number }>
}

export async function getCentralBanks(signal?: AbortSignal): Promise<{ rows: PolicyRate[]; stale: boolean; as_of: string; source: string }> {
  return (await apiClient.get('/macro/central-banks', { signal })).data
}

export interface FlowSide {
  buy: number | null
  sell: number | null
  net: number | null
}

export interface ParticipantPosition {
  index_futures_long: number
  index_futures_short: number
  index_futures_net: number
  index_futures_long_pct: number | null
  index_options_net: number
  stock_futures_net: number
}

export interface IndiaFlows {
  cash: {
    latest: { date: string; fii?: FlowSide; dii?: FlowSide } | null
    series: Array<{ date: string; fii: number | null; dii: number | null }>
    sessions_saved: number
    five_day: { fii: number | null; dii: number | null; sessions: number }
    month_to_date: { fii: number | null; dii: number | null; sessions: number }
    stale: string | null
  }
  positioning: null | {
    date: string
    groups: Record<string, ParticipantPosition>
    previous: Record<string, ParticipantPosition> | null
    fii_long_pct_series: Array<{ date: string; pct: number | null; net: number }>
    fii_long_pct_range: [number, number] | null
    sessions: number
  }
  source: string
}

export async function getIndiaFlows(signal?: AbortSignal): Promise<IndiaFlows> {
  return (await apiClient.get('/macro/india-flows', { signal })).data
}

interface MarketMood {
  market: string
  score: number | null
  label: string | null
  readings: Array<{ key: string; label: string; score: number; value: string; label_text: string | null }>
  universe: string
  index: string
  source: string
  live?: LiveInfo | null
}

export async function getMarketMood(market: string, signal?: AbortSignal): Promise<MarketMood> {
  return (await apiClient.get('/macro/mood', { params: { market }, signal })).data
}
