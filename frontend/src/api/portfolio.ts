import { apiClient } from './client'

export interface Holding {
  symbol: string
  quantity: number
  avg_cost: number
  current_price: number
  market: string
  market_value?: number
  cost_basis?: number
  unrealized_gain?: number
  unrealized_gain_percent?: number
  /** Mutual funds (market "mf"): scheme details from mfapi.in */
  name?: string
  amc?: string
  category?: string
  nav_date?: string
}

export interface PortfolioSummary {
  name: string
  holdings: Record<string, Holding>
  cash_balance: number
  currency: string
  total_market_value: number
  total_cost_basis: number
  total_unrealized_gain: number
  total_unrealized_gain_percent: number
  total_value: number
  transactions?: PortfolioTransaction[]
  /** "stocks" or "funds" (mutual funds). */
  kind?: PortfolioKind
}

export type PortfolioKind = 'stocks' | 'funds'

export interface PortfolioTransaction {
  /** Position in the history - what deleteTransaction takes. */
  index: number
  symbol: string
  transaction_type: TransactionType
  quantity: number
  price: number
  date: string | null
  fees: number
  notes: string
  market: string
  total: number
}

export type TransactionType = 'buy' | 'sell' | 'dividend' | 'split'

interface AddTransactionRequest {
  symbol: string
  transaction_type: TransactionType
  quantity: number
  price: number
  date?: string
  fees?: number
  notes?: string
  market?: string
}

export async function listPortfolios(): Promise<string[]> {
  const res = await apiClient.get<string[]>('/portfolio')
  return res.data
}

export async function getPortfolio(name: string): Promise<PortfolioSummary> {
  const res = await apiClient.get<PortfolioSummary>(`/portfolio/${encodeURIComponent(name)}`)
  return res.data
}

export async function createPortfolio(name: string, currency = 'USD', kind: PortfolioKind = 'stocks'): Promise<PortfolioSummary> {
  const res = await apiClient.post<PortfolioSummary>('/portfolio', { name, currency, kind })
  return res.data
}

export async function addTransaction(
  name: string,
  body: AddTransactionRequest,
): Promise<PortfolioSummary> {
  const res = await apiClient.post<PortfolioSummary>(
    `/portfolio/${encodeURIComponent(name)}/transactions`,
    body,
  )
  return res.data
}

/** Official AMFI NAV of a fund on a date (the last one before it on a holiday). */
export async function getFundNav(code: string, on: string): Promise<{ nav: number; nav_date: string }> {
  const res = await apiClient.get<{ nav: number; nav_date: string }>(`/funds/${encodeURIComponent(code)}/nav`, { params: { on } })
  return res.data
}

export async function renamePortfolio(name: string, newName: string): Promise<PortfolioSummary> {
  const res = await apiClient.patch<PortfolioSummary>(`/portfolio/${encodeURIComponent(name)}`, { name: newName })
  return res.data
}

export async function deletePortfolio(name: string): Promise<void> {
  await apiClient.delete(`/portfolio/${encodeURIComponent(name)}`)
}

/** Remove one transaction; the server rebuilds holdings from the rest. */
export async function deleteTransaction(name: string, index: number): Promise<PortfolioSummary> {
  const res = await apiClient.delete<PortfolioSummary>(`/portfolio/${encodeURIComponent(name)}/transactions/${index}`)
  return res.data
}

export interface MixStats {
  expected_return: number | null
  volatility: number | null
  sharpe: number | null
  /** average daily loss on the worst 5% of days (fraction) */
  cvar_95?: number | null
}

export interface PortfolioAnalytics {
  /** 'analytics' (public users): optimizer is null - a recommended mix is adviser territory. */
  compliance?: 'analytics'
  as_of: string
  days: number
  market: string
  benchmark: { symbol: string; name: string }
  risk_free: number
  total_value: number
  /** Ratios are fractions (0.12 = 12%). var/cvar are 1-day, 95%. */
  metrics: {
    annual_return: number | null
    volatility: number | null
    sharpe: number | null
    sortino: number | null
    max_drawdown: number | null
    var_95: number | null
    cvar_95: number | null
    var_95_value: number | null
    cvar_95_value: number | null
    beta: number | null
    benchmark_return?: number | null
    tracking_error?: number | null
    information_ratio?: number | null
    up_capture?: number | null
    down_capture?: number | null
  }
  /** Estimated moves in past market falls / flat shocks, via each holding's beta (fractions) */
  stress?: Array<{ label: string; index_move: number; portfolio_move: number; from: string | null; to: string | null }>
  /** Default Monte Carlo inputs (fractions a year) */
  projection?: { expected_return: number; volatility: number | null }
  holdings: Array<{
    symbol: string
    weight: number
    annual_return: number
    volatility: number
    max_drawdown: number
    beta: number | null
    risk_contribution: number | null
  }>
  correlation: { symbols: string[]; matrix: (number | null)[][] }
  optimizer: {
    current: MixStats
    max_weight?: number
    max_sharpe?: MixStats & { weights: Record<string, number> }
    risk_parity?: MixStats & { weights: Record<string, number> }
    hrp?: MixStats & { weights: Record<string, number> }
    min_cvar?: MixStats & { weights: Record<string, number> }
    trades?: Array<{ symbol: string; action: 'buy' | 'sell'; current_weight: number; target_weight: number; trade_value: number }>
    suggestions?: string[]
  } | null
  curve: Array<{ time: string; portfolio: number | null; benchmark?: number | null }>
  warnings: string[]
}

export async function getPortfolioAnalytics(name: string): Promise<PortfolioAnalytics> {
  const res = await apiClient.get<PortfolioAnalytics>(`/portfolio/${encodeURIComponent(name)}/analytics`)
  return res.data
}

export interface CasFund {
  amfi: string
  isin: string | null
  scheme: string
  amc: string
  folios: number
  units: number
  nav: number
  cost: number | null
  value: number
  date: string | null
}

export interface CasPreview {
  statement_to: string | null
  cas_type: string
  holdings: CasFund[]
  skipped: Array<{ scheme: string; reason: string }>
  total_value: number
  warnings: string[]
}

/** Read a CAMS / KFintech CAS PDF. Used in memory on the server, never stored. */
export async function parseCas(fileB64: string, password: string): Promise<CasPreview> {
  const res = await apiClient.post<CasPreview>('/portfolio/cas/parse', { file_b64: fileB64, password }, { timeout: 120_000 })
  return res.data
}

export async function importFunds(
  name: string,
  holdings: Array<Pick<CasFund, 'amfi' | 'scheme' | 'units' | 'nav' | 'cost' | 'date'>>,
): Promise<{ applied: number; unchanged: number; portfolio: PortfolioSummary }> {
  const res = await apiClient.post(`/portfolio/${encodeURIComponent(name)}/import-funds`, { holdings })
  return res.data
}

export interface FundInsights {
  funds: number
  total_value?: number
  score?: number
  grade?: 'Good' | 'Fair' | 'Needs attention'
  asset_classes?: Array<{ name: string; weight: number }>
  categories?: Array<{ name: string; weight: number; count: number }>
  similar_pairs?: Array<{ a: string; b: string; a_name: string; b_name: string; correlation: number }>
  issues?: string[]
  method?: string
}

export async function getFundInsights(name: string): Promise<FundInsights> {
  const res = await apiClient.get<FundInsights>(`/portfolio/${encodeURIComponent(name)}/fund-insights`)
  return res.data
}

interface LumpsumCondition {
  key: 'dip' | 'trend' | 'history' | 'market'
  label: string
  pass: boolean
  detail: string
}

export interface LumpsumCheck {
  status: 'ok' | 'short' | 'skipped'
  reason?: string
  level?: 'strong' | 'watch' | 'none'
  met?: number
  total?: number
  conditions?: LumpsumCondition[]
  below_high?: number
  deeper_than_pct?: number
  below_200d?: number
  below_52w_high?: number
  turning?: boolean
  rsi?: number | null
  after_dips_1y?: number | null
  typical_1y?: number
  win_rate?: number | null
  recovery_days?: number | null
  as_of?: string
}

export interface FundRow {
  code: string
  name: string
  amc?: string
  category: string
  asset_class: string
  units: number
  nav: number | null
  nav_date?: string
  invested: number
  value: number
  gain: number
  gain_pct: number
  xirr_pct: number | null
  best_sip_day?: number | null
  sip_edge?: string | null
  lumpsum: LumpsumCheck
}

export interface PortfolioFunds {
  funds: FundRow[]
  total: { invested: number; value: number; gain: number; xirr_pct: number | null }
  compliance: 'analytics'
}

/** Mutual fund view: per fund value, XIRR, best SIP day and lumpsum window check. */
export async function getPortfolioFunds(name: string): Promise<PortfolioFunds> {
  return (await apiClient.get<PortfolioFunds>(`/portfolio/${encodeURIComponent(name)}/funds`, { timeout: 120_000 })).data
}

export interface FundAiReview {
  view: 'strong window' | 'reasonable' | 'wait' | null
  summary: string
  reasons: string[]
  risk: string | null
}

export async function getFundAiReview(portfolio: string, code: string): Promise<FundAiReview> {
  return (
    await apiClient.post<FundAiReview>(`/portfolio/${encodeURIComponent(portfolio)}/funds/${encodeURIComponent(code)}/ai-review`, null, {
      timeout: 120_000,
    })
  ).data
}

export interface DipRules {
  /** % below the 52-week high for the portfolio's funds, e.g. [5, 7.5, 10]. */
  levels: number[]
  /** Fund code -> its own levels ([] = no % alerts for that fund). */
  overrides: Record<string, number[]>
  choices: number[]
}

export async function getDipRules(portfolio: string): Promise<DipRules> {
  return (await apiClient.get<DipRules>(`/portfolio/${encodeURIComponent(portfolio)}/dip-alerts`)).data
}

export async function setDipRules(portfolio: string, rules: { levels: number[]; overrides: Record<string, number[]> }): Promise<DipRules> {
  return (await apiClient.put<DipRules>(`/portfolio/${encodeURIComponent(portfolio)}/dip-alerts`, rules)).data
}

export async function sendTestDipAlert(portfolio: string): Promise<{ fund: string }> {
  return (await apiClient.post<{ fund: string }>(`/portfolio/${encodeURIComponent(portfolio)}/dip-alerts/test`, null, { timeout: 90_000 })).data
}

export type ReviewSeverity = 'high' | 'medium' | 'low'

export interface ReviewFinding {
  id: string
  severity: ReviewSeverity
  title: string
  /** What we see, with the numbers. */
  fact: string
  /** Why it matters. */
  why: string
  /** What the user can change. */
  levers: string[]
  /** Card id on the Portfolio page with the detail. */
  section: string
  /** The user's own limit this was checked against. */
  rule: string | null
  symbols: string[]
}

export interface ReviewLimits {
  max_holding: number
  max_sector: number
  max_cash: number
  loss_review: number
  min_holdings: number
}

export interface PortfolioReview {
  score: number | null
  grade: 'Good' | 'Fair' | 'Needs attention' | null
  summary: string
  findings: ReviewFinding[]
  good: string[]
  limits: ReviewLimits
  as_of?: string | null
}

export interface PortfolioReviewAi {
  summary: string
  priorities: string[]
  keep?: string | null
}

export async function getPortfolioReview(name: string): Promise<PortfolioReview> {
  const res = await apiClient.get<PortfolioReview>(`/portfolio/${encodeURIComponent(name)}/review`, { timeout: 120_000 })
  return res.data
}

export async function setReviewLimits(name: string, limits: Partial<ReviewLimits>): Promise<ReviewLimits> {
  const res = await apiClient.put<ReviewLimits>(`/portfolio/${encodeURIComponent(name)}/review/limits`, limits)
  return res.data
}

export async function getPortfolioReviewAi(name: string): Promise<PortfolioReviewAi> {
  const res = await apiClient.post<PortfolioReviewAi>(`/portfolio/${encodeURIComponent(name)}/review/ai`, null, { timeout: 120_000 })
  return res.data
}

export interface ReconcileFix {
  type: 'buy' | 'sell' | 'split'
  quantity: number
  price: number
  date: string
  notes: string
  /** the price is a placeholder (today's price): the user should type the real one */
  needs_price?: boolean
}

export interface ReconcileLine {
  symbol: string
  market: string
  name: string
  statement_qty: number
  app_qty: number
  diff: number
  statement_avg: number | null
  app_avg: number | null
}

export interface ReconcileBreak extends ReconcileLine {
  kind: 'not_in_app' | 'not_in_statement' | 'split' | 'short' | 'excess'
  cause: string
  fixes: ReconcileFix[]
}

export interface ReconcileReport {
  kind: 'broker' | 'cas'
  rows_read: number
  unresolved: { symbol: string; name: string; isin: string; quantity: number }[]
  matches: ReconcileLine[]
  breaks: ReconcileBreak[]
  cost_differences: (ReconcileLine & { cause: string })[]
  ledger: { symbol: string | null; stored?: number; from_history?: number; issue: string }[]
}

export async function reconcilePortfolio(name: string, filename: string, fileB64: string, password: string): Promise<ReconcileReport> {
  const res = await apiClient.post<ReconcileReport>(
    `/portfolio/${encodeURIComponent(name)}/reconcile`,
    { filename, file_b64: fileB64, password },
    { timeout: 120_000 },
  )
  return res.data
}

export async function applyReconcileFixes(
  name: string,
  fixes: Array<Omit<ReconcileFix, 'needs_price'> & { symbol: string; market: string }>,
): Promise<{ applied: number; errors: string[]; portfolio: PortfolioSummary }> {
  const res = await apiClient.post(`/portfolio/${encodeURIComponent(name)}/reconcile/apply`, { fixes })
  return res.data
}

export interface FundsAiReview {
  summary: string
  strengths: string[]
  concerns: string[]
  sections: Partial<Record<'mix' | 'overlap' | 'concentration' | 'risk', string>>
  funds: { code: string; note: string; name: string | null; weight_pct: number | null }[]
  view: 'strong' | 'fair' | 'weak' | null // owner only
  actions: string[] // owner only
  look_through: { covered_pct: number | null; top_stocks_of_portfolio?: string[]; top_sectors_of_portfolio?: string[] } | null
  generated_at: string
  compliance: 'analytics'
}

export async function getFundsAiReview(name: string, refresh = false): Promise<FundsAiReview> {
  return (await apiClient.post<FundsAiReview>(`/portfolio/${encodeURIComponent(name)}/funds/ai-review`, null, { params: { refresh }, timeout: 260_000 })).data
}
