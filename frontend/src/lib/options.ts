// Option lists mirrored from the backend: Markets enum
// (src/core/constants.py) and MODE_CHAINS (src/agent/orchestrator.py).

export interface Option<T extends string = string> {
  value: T
  label: string
  hint?: string
  /** Shown but not selectable (e.g. needs a higher plan). */
  disabled?: boolean
  /** Small tag after the label, e.g. "Pro". */
  badge?: string
}

export const MARKETS: Option[] = [
  { value: 'us', label: 'US', hint: 'NYSE / NASDAQ' },
  { value: 'india', label: 'India', hint: 'NSE / BSE' },
  { value: 'china_a', label: 'China A', hint: 'Shanghai / Shenzhen' },
  { value: 'hong_kong', label: 'Hong Kong', hint: 'HKEX' },
  { value: 'crypto', label: 'Crypto', hint: 'e.g. BTC-USD' },
  { value: 'global', label: 'Global', hint: 'Any global ticker, e.g. SHEL.L or 7203.T' },
]

/** AI analysis depth (src/agent/orchestrator.py); each level adds to the one before. */
export const MODES: Option[] = [
  { value: 'quick', label: 'Quick', hint: 'Fastest. Chart only: Technical → AI summary' },
  { value: 'standard', label: 'Standard', hint: 'Adds risk and recent news: Technical → Risk → News → AI summary' },
  {
    value: 'full',
    label: 'Full',
    hint: 'Adds the business: Technical → Risk → News → Fundamentals (filings, valuation vs sector, analyst estimates) → AI summary',
  },
  {
    value: 'specialist',
    label: 'Specialist',
    hint: 'Slowest, most thorough. Full plus up to 3 strategy agents before the AI summary',
  },
]

export const PERIODS: Option[] = [
  { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: 'ytd', label: 'YTD' },
  { value: '1y', label: '1Y' },
  { value: '5y', label: '5Y' },
]

export const CURRENCIES = ['USD', 'INR', 'EUR', 'GBP', 'CNY', 'HKD', 'JPY']

export function labelFor(options: Option[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value
}
