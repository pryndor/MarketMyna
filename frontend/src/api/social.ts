import { apiClient } from './client'

export type SocialTone = 'bullish' | 'neutral' | 'bearish'
export type SocialMood = 'very bullish' | 'bullish' | 'neutral' | 'bearish' | 'very bearish'

export interface SocialSourceStatus {
  source: string
  label: string
  status: 'ok' | 'empty' | 'blocked' | 'skipped' | 'error'
  posts: number
  via: string | null
  message: string | null
}

export interface SocialPost {
  source: string
  id: string
  title: string
  excerpt: string
  url: string
  created_at: string
  author: string
  community: string
  score: number
  comments: number
  label: 'bullish' | 'bearish' | null
  sentiment: number
  tone: SocialTone
  terms: string[]
}

export interface SocialSentiment {
  symbol: string
  market: string
  query: { ticker: string; name: string; aliases: string[] }
  fetched_at: string
  window_days: number
  sources: SocialSourceStatus[]
  score: number
  mood: SocialMood | null
  confidence: 'low' | 'medium' | 'high'
  posts: number
  counts: Record<SocialTone, number>
  by_source: Array<{ source: string; label: string; posts: number; score: number }>
  themes: Array<{ theme: string; posts: number; score: number; tone: SocialTone }>
  timeline: Array<{ day: string; posts: number; score: number | null }>
  buzz: { last_24h: number; daily_avg: number; ratio: number } | null
  top_posts: SocialPost[]
  history: Array<{ day: string; score: number; posts: number }>
}

export interface SocialSummary {
  symbol: string
  posts: number
  summary: string
  bull_points: string[]
  bear_points: string[]
  hype_risk: 'low' | 'medium' | 'high'
  hype_reason: string
}

export async function getSocialSentiment(symbol: string, market = 'us', refresh = false): Promise<SocialSentiment> {
  const res = await apiClient.get<SocialSentiment>(`/stocks/${encodeURIComponent(symbol)}/social`, {
    params: { market, ...(refresh ? { refresh: true } : {}) },
  })
  return res.data
}

export async function getSocialSummary(symbol: string, market = 'us'): Promise<SocialSummary> {
  const res = await apiClient.post<SocialSummary>(`/stocks/${encodeURIComponent(symbol)}/social/ai-summary`, null, {
    params: { market },
  })
  return res.data
}
