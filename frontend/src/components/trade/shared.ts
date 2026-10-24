export const SERIES_COLORS: Record<string, string> = {
  vwap: '#f5b942',
  ema9: '#6d8cff',
  ema21: '#c77dff',
  ema50: '#22d3ee',
  ema200: '#f472b6',
  vwma13: '#38bdf8',
  vwma19: '#fbbf24',
}

export interface PriceLevel {
  price: number
  label: string
  color: string
  dashed?: boolean
}

export const CURRENCY: Record<string, string> = {
  india: 'INR',
  us: 'USD',
  china_a: 'CNY',
  hong_kong: 'HKD',
  crypto: 'USD',
  global: 'USD',
}
