import { UNAUTHORIZED_EVENT } from './auth'
import { apiClient } from './client'

export interface AgentOpinion {
  agent_name: string
  summary: string
  signal: string | null
  confidence: number | null
  details: Record<string, unknown>
}

export interface Dashboard {
  symbol: string
  market: string
  mode: string
  /** Login area the AI decision was written for (null = area-neutral). */
  area?: 'trader' | 'investor' | null
  /** Always 'analytics': no decision, target or stop (src/core/compliance.py). */
  compliance?: 'analytics'
  /** The AI's summary as a direction, never a call. */
  outlook?: 'bullish' | 'neutral' | 'bearish' | null
  analysis_summary: string | null
  risk_level: string | null
  opinions: AgentOpinion[]
  generated_at: string
}

interface AnalyzeRequest {
  symbol: string
  market?: string
  mode?: string
  area?: 'trader' | 'investor' | null
}

export type StreamEvent =
  | { event: 'stage_start'; agent: string }
  | { event: 'stage_done'; agent: string; opinion: AgentOpinion }
  | { event: 'stage_skipped'; agent: string; message: string }
  | { event: 'done'; dashboard: Dashboard }
  | { event: 'error'; message: string }

/**
 * The streaming endpoint is POST, so the browser's EventSource (GET-only)
 * can't be used - this reads the response body as a stream and parses
 * `data: {...}\n\n` frames by hand, calling `onEvent` for each one as it
 * arrives rather than waiting for the whole response.
 */
export async function analyzeStream(
  body: AnalyzeRequest,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/v1/agent/analyze/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  if (!response.ok || !response.body) {
    // The API's error envelope ({message}) says why, e.g. no AI model set up.
    const data = (await response.json().catch(() => null)) as { message?: string } | null
    throw new Error(data?.message || `Stream request failed: HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let separatorIndex: number
    while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
      const rawFrame = buffer.slice(0, separatorIndex)
      buffer = buffer.slice(separatorIndex + 2)

      const dataLine = rawFrame.split('\n').find((line) => line.startsWith('data: '))
      if (!dataLine) continue

      try {
        onEvent(JSON.parse(dataLine.slice('data: '.length)) as StreamEvent)
      } catch {
        // A malformed frame shouldn't kill the whole stream - skip it.
        continue
      }
    }
  }
}

/** Whether Run AI can work here: a saved AI key, or a model set in config / env (a local Ollama). */
export async function getAiStatus(): Promise<{ configured: boolean }> {
  return (await apiClient.get<{ configured: boolean }>('/agent/status')).data
}
