import { apiClient } from './client'
import type { SmartRow } from './scheduler'

// ---------------------------------------------------------------- chart

export interface Bar {
  time: number // exchange wall-clock seconds
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface ChartData {
  symbol: string
  market: string
  interval: string
  period: string
  bars: Bar[]
  series: Record<string, Array<{ time: number; value: number }>>
  pivots: Record<'R3' | 'R2' | 'R1' | 'P' | 'S1' | 'S2' | 'S3', number> | null
  opening_range: { high: number; low: number } | null
  /** experimental kNN indicators: crossover / entry / exit arrows */
  markers?: Array<{ time: number; kind: 'buy' | 'sell' | 'buy_skip' | 'sell_skip'; text: string }>
  /** latest kNN reading: lean -1..1, agreement 0..1, adaptive Supertrend direction */
  knn?: { score: number; agree: number; trend: 'up' | 'down' } | null
  last: { time: number; close: number; rsi: number | null } | null
}

export async function getTradeChart(
  symbol: string,
  market: string,
  interval: string,
  period: string | undefined,
  indicators: string[],
): Promise<ChartData> {
  const res = await apiClient.get<ChartData>('/trade/chart', {
    params: { symbol, market, interval, period, indicators: indicators.join(',') },
  })
  return res.data
}

export async function getLevels(symbol: string, market: string): Promise<SmartRow> {
  return (await apiClient.get<SmartRow>('/trade/levels', { params: { symbol, market } })).data
}

// ---------------------------------------------------------------- alerts

export type AlertKind =
  | 'price_above'
  | 'price_below'
  | 'pct_up'
  | 'pct_down'
  | 'rsi_above'
  | 'rsi_below'
  | 'volume_spike'
  | 'high_breakout'
  | 'low_breakdown'

export interface AlertKindInfo {
  kind: AlertKind
  label: string
  unit: 'price' | '%' | 'rsi' | 'x avg' | 'days'
}

export interface PriceAlert {
  id: number
  symbol: string
  market: string
  kind: AlertKind
  value: number
  note: string
  status: 'active' | 'paused' | 'triggered' | 'expired'
  repeat: boolean
  armed: boolean
  cooldown_minutes: number
  expires_at: string | null
  created_at: string
  last_checked_at: string | null
  last_value: number | null
  last_triggered_at: string | null
  trigger_count: number
  description: string
}

interface NewAlert {
  symbol: string
  market: string
  kind: AlertKind
  value: number
  note?: string
  repeat?: boolean
  cooldown_minutes?: number
}

export interface AlertEvent {
  id: number
  alert_id: number
  symbol: string
  market: string
  kind: string
  message: string
  price: number | null
  delivery: Record<string, boolean>
  created_at: string
}

export async function getAlertKinds(): Promise<AlertKindInfo[]> {
  return (await apiClient.get<AlertKindInfo[]>('/trade/alert-kinds')).data
}

export async function listAlerts(): Promise<PriceAlert[]> {
  return (await apiClient.get<PriceAlert[]>('/trade/alerts')).data
}

export async function createAlert(alert: NewAlert): Promise<PriceAlert> {
  return (await apiClient.post<PriceAlert>('/trade/alerts', alert)).data
}

export async function updateAlert(
  id: number,
  patch: Partial<Pick<PriceAlert, 'value' | 'note' | 'repeat' | 'cooldown_minutes'>> & { status?: 'active' | 'paused' },
): Promise<PriceAlert> {
  return (await apiClient.patch<PriceAlert>(`/trade/alerts/${id}`, patch)).data
}

export async function deleteAlert(id: number): Promise<void> {
  await apiClient.delete(`/trade/alerts/${id}`)
}

export async function listAlertEvents(limit = 50): Promise<AlertEvent[]> {
  return (await apiClient.get<AlertEvent[]>('/trade/alerts/events', { params: { limit } })).data
}

interface CheckResult {
  checked: number
  skipped_closed: number
  fired: Array<{ id: number; symbol: string; observed: string }>
}

export async function checkAlertsNow(): Promise<CheckResult> {
  return (await apiClient.post<CheckResult>('/trade/alerts/check')).data
}

export async function getAlertMonitorStatus(): Promise<{ running: boolean; poll_seconds: number | null }> {
  return (await apiClient.get('/trade/alerts/status')).data
}

// ---------------------------------------------------------------- journal

export interface Trade {
  id: number
  symbol: string
  market: string
  side: 'long' | 'short'
  quantity: number
  entry_price: number
  entry_at: string
  exit_price: number | null
  exit_at: string | null
  stop: number | null
  target: number | null
  fees: number
  fees_auto: boolean | null
  product: Product | null
  setup: string
  notes: string
  pnl: number | null
  r_multiple: number | null
}

export type NewTrade = Omit<Trade, 'id' | 'pnl' | 'r_multiple' | 'entry_at' | 'exit_at' | 'fees' | 'fees_auto'> & {
  /** null = estimate from the charges schedule */
  fees: number | null
  entry_at?: string
  exit_at?: string
}

export interface JournalStats {
  closed: number
  open: number
  wins: number
  losses: number
  win_rate: number | null
  total_pnl: number
  avg_win: number | null
  avg_loss: number | null
  profit_factor: number | null
  expectancy: number | null
  avg_r: number | null
  best: number | null
  worst: number | null
  max_losing_streak: number
  by_setup: Array<{ setup: string; trades: number; win_rate: number; pnl: number }>
  equity: Array<{ date: string; pnl: number }>
}

export interface JournalData {
  trades: Trade[]
  stats: JournalStats
  markets: string[]
}

export async function getJournal(market?: string): Promise<JournalData> {
  return (await apiClient.get<JournalData>('/trade/journal', { params: market ? { market } : {} })).data
}

export async function addTrade(trade: Partial<NewTrade>): Promise<Trade> {
  return (await apiClient.post<Trade>('/trade/journal', trade)).data
}

export async function updateTrade(id: number, patch: Partial<NewTrade>): Promise<Trade> {
  return (await apiClient.patch<Trade>(`/trade/journal/${id}`, patch)).data
}

export async function deleteTrade(id: number): Promise<void> {
  await apiClient.delete(`/trade/journal/${id}`)
}

// ---------------------------------------------------------------- scanner

export interface ScanInfo {
  id: string
  label: string
  group: string
  intraday: boolean
  default: number | null
  param: string | null
}

export interface Universe {
  sources: Array<'top' | 'watchlist' | 'portfolio' | 'custom'>
  market: string
  top_n: number
  watchlist_ids: number[]
  portfolio_names: string[]
  symbols: string[]
}

export interface ScanRequest {
  universe: Universe
  scans: string[]
  params: Record<string, number>
  match: 'any' | 'all'
}

export interface ScanRow {
  symbol: string
  market: string
  name?: string | null
  price: number
  change_percent: number
  gap_percent: number
  volume_ratio: number | null
  rsi: number | null
  high_52w?: number
  low_52w?: number
  matched: string[]
  reasons: string[]
}

export interface ScanResult {
  rows: ScanRow[]
  scanned: number
  failed: string[]
  seconds: number
}

export interface SavedScan extends ScanRequest {
  id: number
  name: string
  notify: boolean
  interval_minutes: number
  last_run_at: string | null
  last_count: number | null
}

export async function getScanCatalog(): Promise<ScanInfo[]> {
  return (await apiClient.get<ScanInfo[]>('/trade/scans/catalog')).data
}

export async function runScan(req: ScanRequest): Promise<ScanResult> {
  return (await apiClient.post<ScanResult>('/trade/scan', req, { timeout: 180_000 })).data
}

export async function listSavedScans(): Promise<SavedScan[]> {
  return (await apiClient.get<SavedScan[]>('/trade/scans/saved')).data
}

export async function saveScan(scan: ScanRequest & { name: string; notify: boolean; interval_minutes: number }): Promise<SavedScan> {
  return (await apiClient.post<SavedScan>('/trade/scans/saved', scan)).data
}

export async function updateSavedScan(id: number, patch: Partial<SavedScan>): Promise<SavedScan> {
  return (await apiClient.patch<SavedScan>(`/trade/scans/saved/${id}`, patch)).data
}

export async function deleteSavedScan(id: number): Promise<void> {
  await apiClient.delete(`/trade/scans/saved/${id}`)
}

// ---------------------------------------------------------------- backtest

export interface StrategyInfo {
  id: string
  label: string
  description: string
  params: Record<string, number>
  grid: Record<string, number[]>
}

export interface BacktestRequest {
  symbol: string
  market: string
  interval: '1d' | '1wk' | '1h'
  period: '1y' | '2y' | '5y' | '10y' | 'max'
  strategy: string
  params: Record<string, number>
  capital: number
  sizing: 'percent' | 'risk'
  position_pct: number
  risk_pct: number
  stop_type: 'none' | 'percent' | 'atr'
  stop_value: number
  target_r: number | null
  cost_pct: number
  slippage_pct: number
  allow_short: boolean
  optimize: boolean
  objective: 'sharpe' | 'total_return' | 'profit_factor' | 'cagr'
}

export interface BacktestMetrics {
  total_return: number
  cagr: number | null
  max_drawdown: number
  sharpe: number | null
  trades: number
  win_rate: number | null
  profit_factor: number | null
  avg_trade_pct: number | null
  avg_r: number | null
  best_trade: number | null
  worst_trade: number | null
  avg_bars: number | null
  exposure: number | null
  buy_hold_return: number
  final_equity: number
  start: string
  end: string
  bars: number
}

export interface BacktestTrade {
  side: 'long' | 'short'
  entry_time: string
  exit_time: string
  entry: number
  exit: number
  quantity: number
  pnl: number
  return_pct: number
  r: number | null
  bars: number
  reason: string
}

export interface BacktestResult {
  symbol: string
  market: string
  interval: string
  period: string
  params: Record<string, number>
  metrics: BacktestMetrics
  equity: Array<{ time: string; equity: number; buy_hold: number; drawdown: number }>
  trades: BacktestTrade[]
  split: { train: BacktestMetrics; test: BacktestMetrics }
  optimization?: {
    objective: string
    best: Record<string, number>
    keys: string[]
    test: BacktestMetrics
    grid: Array<{ params: Record<string, number>; score: number | null; total_return: number; sharpe: number | null; trades: number }>
  }
}

export async function getStrategies(): Promise<StrategyInfo[]> {
  return (await apiClient.get<StrategyInfo[]>('/trade/backtest/strategies')).data
}

export async function runBacktest(req: BacktestRequest): Promise<BacktestResult> {
  return (await apiClient.post<BacktestResult>('/trade/backtest', req, { timeout: 180_000 })).data
}

// ---------------------------------------------------------------- options

export interface OptionLeg {
  ltp: number | null
  change: number | null
  oi: number | null
  chg_oi: number | null
  volume: number | null
  iv: number | null
  iv_estimated?: boolean
  bid: number | null
  ask: number | null
  delta?: number
  gamma?: number
  theta?: number
  vega?: number
}

export interface OptionRow {
  strike: number
  call?: OptionLeg
  put?: OptionLeg
}

export interface OptionChain {
  symbol: string
  market: string
  expiries: string[]
  timestamp: string
  lot_size: number | null
  rows: OptionRow[]
  summary: {
    spot: number
    expiry: string
    days_to_expiry: number
    atm_strike: number | null
    atm_iv: number | null
    expected_move: number | null
    pcr_oi: number | null
    pcr_volume: number | null
    max_pain: number | null
    support: number | null
    resistance: number | null
    call_oi: number
    put_oi: number
    rate: number
  }
  /** Dealer gamma exposure (calls +, puts -), money per 1% move */
  gex?: {
    total: number
    zero_gamma: number | null
    peak_strike: number | null
    multiplier: number
    by_strike: Array<{ strike: number; call: number; put: number; net: number }>
    interpolated_iv: boolean
  } | null
  /** OTM IV by strike, solved against the parity-implied forward */
  smile?: { forward: number | null; points: Array<{ strike: number; iv: number; side: 'call' | 'put' }>; same_day: boolean } | null
  /** ATM implied vol vs the underlying's realized vol (all in %) */
  vol_compare?: {
    rv_20: number
    rv_60: number | null
    rv_20_low: number
    rv_20_high: number
    atm_iv: number | null
    ratio: number | null
    iv_vs_rv_range_pct: number | null
    verdict: 'cheap' | 'fair' | 'expensive' | null
  } | null
}

export interface PayoffLeg {
  type: 'call' | 'put' | 'stock'
  side: 'buy' | 'sell'
  strike: number
  premium: number
  quantity: number
  iv?: number | null
}

export interface PayoffResult {
  points: Array<{ price: number; expiry: number; today: number }>
  breakevens: number[]
  max_profit: number | null
  max_loss: number | null
  net_premium: number
  greeks: { delta: number; gamma: number; theta: number; vega: number }
}

export async function getOptionChain(symbol: string, market: string, expiry?: string): Promise<OptionChain> {
  return (await apiClient.get<OptionChain>('/trade/options/chain', { params: { symbol, market, expiry } })).data
}

export async function getPayoff(body: { legs: PayoffLeg[]; spot: number; days: number; market: string; width_pct?: number }): Promise<PayoffResult> {
  return (await apiClient.post<PayoffResult>('/trade/options/payoff', body)).data
}

// ---------------------------------------------------------------- daily risk

export interface RiskSettings {
  market: string
  capital: number
  daily_loss_limit_pct: number
  max_open_risk_pct: number
  max_trades_per_day: number
  notify: boolean
}

export interface RiskStatus {
  settings: RiskSettings
  status: 'ok' | 'warn' | 'stop'
  reasons: string[]
  day_pnl: number
  realized: number
  unrealized: number
  loss_limit: number
  limit_used_pct: number | null
  open_risk: number
  open_risk_pct: number | null
  max_open_risk: number
  trades_today: number
  closed_today: number
  positions: Array<{ id: number; symbol: string; side: string; quantity: number; entry_price: number; stop: number | null; price: number | null; pnl: number | null }>
}

export async function getRisk(): Promise<RiskStatus> {
  return (await apiClient.get<RiskStatus>('/trade/risk')).data
}

export async function saveRiskSettings(patch: Partial<RiskSettings>): Promise<RiskSettings> {
  return (await apiClient.put<RiskSettings>('/trade/risk/settings', patch)).data
}

// ---------------------------------------------------------------- charges & lots

export type Product = 'intraday' | 'delivery' | 'futures' | 'options'

export interface Charges {
  total: number
  parts: Record<string, number>
  rates_as_of: string
}

export async function estimateCharges(body: {
  market: string
  product?: Product
  buy_value: number
  sell_value: number
  quantity?: number
  commission_pct?: number
  flat?: number
}): Promise<Charges> {
  return (await apiClient.post<Charges>('/trade/charges', body)).data
}

export async function getLotSize(symbol: string): Promise<number | null> {
  return (await apiClient.get<{ lot_size: number | null }>('/trade/lot-size', { params: { symbol } })).data.lot_size
}

export interface MarketStatus {
  market: string
  name: string
  open: boolean
  always_open: boolean
  timezone?: string
  next_change?: string
  next_change_label?: string
  session?: string
  delay: string
}

export async function getMarketStatus(market: string): Promise<MarketStatus> {
  return (await apiClient.get<MarketStatus>('/trade/market-status', { params: { market } })).data
}

export interface PairsResult {
  a: string
  b: string
  market: string
  market_b: string
  period: string
  days: number
  start: string
  end: string
  hedge_ratio: number
  correlation: number
  adf_stat: number
  adf_lag: number
  critical: Record<string, number>
  significance: '1%' | '5%' | '10%' | null
  half_life_days: number | null
  z_now: number
  verdict: 'cointegrated' | 'stretched' | 'not_cointegrated'
  spread: Array<{ time: string; z: number }>
}

export async function getPairs(params: { a: string; b: string; market: string; market_b?: string; period: string }): Promise<PairsResult> {
  return (await apiClient.get<PairsResult>('/trade/pairs', { params, timeout: 60_000 })).data
}
