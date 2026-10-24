import { apiClient } from './client'

export interface ScreenPreset {
  key: string
  title: string
  description: string
  large_only: boolean
  rules: string[]
}

export interface ScreenResult {
  key: string
  title: string
  description: string
  market: string
  rules: string[]
  columns: Array<{ key: string; label: string }>
  universe: string
  scanned: number
  results: Array<{ symbol: string; name: string | null; market: string; market_cap: number | null; volume?: number | null; price: number | null; currency: string | null; change_percent: number | null; sector: string | null } & Record<string, number | string | null>>
}

/** What a screen runs over: a market's stocks (crypto: its coins) or its ETFs. */
export type ScreenAsset = 'stock' | 'etf'

export async function listScreens(market = 'india', asset: ScreenAsset = 'stock'): Promise<ScreenPreset[]> {
  return (await apiClient.get<ScreenPreset[]>('/screens', { params: { market, asset } })).data
}

export async function runScreen(key: string, market: string, asset: ScreenAsset = 'stock'): Promise<ScreenResult> {
  return (await apiClient.get<ScreenResult>(`/screens/${key}`, { params: { market, asset }, timeout: 120_000 })).data
}

export type ScreenOp = '>' | '<' | 'between' | 'top' | 'bottom' | 'below_sector' | 'above_sector'

export interface ScreenRule {
  field: string
  op: ScreenOp
  value: number | null
  value2?: number | null
}

export interface CustomScreen {
  rules: ScreenRule[]
  sectors: string[]
  sort?: string | null
  descending: boolean
  columns: string[]
  large_only: boolean
}

export interface MetricGroup {
  group: string
  metrics: Array<{ key: string; label: string; hint: string }>
}

export async function listScreenMetrics(): Promise<MetricGroup[]> {
  return (await apiClient.get<MetricGroup[]>('/screens/metrics')).data
}

export async function runCustomScreen(spec: CustomScreen, market: string): Promise<ScreenResult & { sectors: string[] }> {
  return (await apiClient.post<ScreenResult & { sectors: string[] }>('/screens/custom', { ...spec, market }, { timeout: 120_000 })).data
}
