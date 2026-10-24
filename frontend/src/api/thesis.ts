import { apiClient } from './client'

export type PillarStatus = 'on_track' | 'watch' | 'broken'
export type Impact = 'strengthens' | 'weakens' | 'neutral'
export type Conviction = 'high' | 'medium' | 'low'

export interface ThesisLogEntry {
  date: string
  note: string
  impact: Impact
  conviction: Conviction
}

export interface ThesisSignal {
  tone: 'up' | 'down' | 'warn' | 'info'
  key: string
  text: string
}

export interface Thesis {
  id: number
  symbol: string
  market: string
  statement: string
  pillars: { text: string; status: PillarStatus }[]
  risks: string[]
  exit_below: number | null
  exit_note: string
  target: number | null
  conviction: Conviction
  log: ThesisLogEntry[]
  created_at: string | null
  reviewed_at: string | null
  price?: number | null
  signals?: ThesisSignal[]
}

export type ThesisPatch = Partial<Pick<Thesis, 'statement' | 'pillars' | 'risks' | 'exit_note' | 'conviction'>> & {
  exit_below?: number
  target?: number
  clear_exit?: boolean
  clear_target?: boolean
}

export async function getThesis(symbol: string, market: string): Promise<Thesis | null> {
  return (await apiClient.get<{ thesis: Thesis | null }>(`/theses/${encodeURIComponent(symbol)}`, { params: { market }, timeout: 90_000 })).data.thesis
}

export async function saveThesis(symbol: string, market: string, patch: ThesisPatch): Promise<Thesis> {
  return (await apiClient.put<{ thesis: Thesis }>('/theses', { symbol, market, ...patch }, { timeout: 90_000 })).data.thesis
}

export async function addThesisLog(id: number, note: string, impact: Impact, conviction?: Conviction): Promise<Thesis> {
  return (await apiClient.post<{ thesis: Thesis }>(`/theses/${id}/log`, { note, impact, conviction }, { timeout: 90_000 })).data.thesis
}

export async function markThesisReviewed(id: number): Promise<Thesis> {
  return (await apiClient.post<{ thesis: Thesis }>(`/theses/${id}/reviewed`, {}, { timeout: 90_000 })).data.thesis
}

export async function deleteThesis(id: number): Promise<void> {
  await apiClient.delete(`/theses/${id}`)
}
