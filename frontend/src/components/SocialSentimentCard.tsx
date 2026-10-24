import { useEffect, useState, type ReactNode } from 'react'
import { Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  getSocialSentiment,
  getSocialSummary,
  type SocialMood,
  type SocialPost,
  type SocialSentiment,
  type SocialSourceStatus,
  type SocialSummary,
  type SocialTone,
} from '../api/social'
import { cx } from '../lib/cx'
import { compact, errorMessage, relativeTime } from '../lib/format'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Icon, Skeleton } from './ui'

type Tone = 'up' | 'down' | 'warn' | 'neutral' | 'accent'

const MOOD_TONE: Record<SocialMood, Tone> = {
  'very bullish': 'up',
  bullish: 'up',
  neutral: 'warn',
  bearish: 'down',
  'very bearish': 'down',
}
const TONE_TEXT: Record<SocialTone, string> = { bullish: 'text-up', neutral: 'text-muted', bearish: 'text-down' }
const TONE_BG: Record<SocialTone, string> = { bullish: 'bg-up', neutral: 'bg-faint', bearish: 'bg-down' }
const HYPE_TONE: Record<SocialSummary['hype_risk'], Tone> = { low: 'up', medium: 'warn', high: 'down' }
const STATUS_NOTE: Record<SocialSourceStatus['status'], string> = {
  ok: '',
  empty: 'no recent posts',
  blocked: 'blocked / rate-limited',
  skipped: 'not used',
  error: 'failed',
}

function signedScore(n: number) {
  return n > 0 ? `+${n}` : String(n)
}

function scoreClass(n: number | null) {
  if (n == null) return 'text-muted'
  return n >= 10 ? 'text-up' : n <= -10 ? 'text-down' : 'text-muted'
}

/** One headline metric. Every column has the same four rows - label,
 * value, meter, caption - so the meters line up across the grid. */
function Metric({ label, value, meter, caption }: { label: ReactNode; value: ReactNode; meter: ReactNode; caption: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="tabular mt-1 flex h-8 items-baseline text-2xl font-semibold">{value}</div>
      <div className="mt-2 flex h-3.5 items-center">{meter}</div>
      <div className="mt-1.5 text-[12px] text-faint">{caption}</div>
    </div>
  )
}

/** -100..100 scale with a marker at the score. */
function ScoreScale({ score }: { score: number }) {
  const left = `${(Math.max(-100, Math.min(100, score)) + 100) / 2}%`
  return (
    <div className="relative h-1.5 w-full rounded-full bg-gradient-to-r from-down via-faint to-up opacity-80">
      <span
        className="absolute top-1/2 h-3.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-fg ring-2 ring-surface"
        style={{ left }}
      />
    </div>
  )
}

const MOOD_ORDER: SocialTone[] = ['bullish', 'neutral', 'bearish']

function SplitBar({ counts, total }: { counts: SocialSentiment['counts']; total: number }) {
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-line">
      {MOOD_ORDER.map((t) =>
        counts[t] ? <div key={t} className={TONE_BG[t]} style={{ width: `${(counts[t] / total) * 100}%` }} /> : null,
      )}
    </div>
  )
}

/** 0..3x normal volume, with a tick at 1x. */
function BuzzBar({ ratio }: { ratio: number | null }) {
  return (
    <div className="relative h-1.5 w-full rounded-full bg-line">
      {ratio != null && (
        <div
          className={cx('h-full rounded-full', ratio >= 2 ? 'bg-warn' : 'bg-accent')}
          style={{ width: `${Math.min(ratio / 3, 1) * 100}%` }}
        />
      )}
      <span className="absolute top-1/2 left-1/3 h-3.5 w-px -translate-y-1/2 bg-line-strong" title="normal volume" />
    </div>
  )
}

function TrendChart({ data }: { data: SocialSentiment }) {
  const [range, setRange] = useState<'7d' | '30d'>('7d')
  const hasHistory = data.history.length >= 3
  const rows =
    range === '30d' && hasHistory
      ? data.history.map((h) => ({ day: h.day, score: h.score, posts: h.posts }))
      : data.timeline.map((t) => ({ day: t.day, score: t.score, posts: t.posts }))
  if (!rows.some((r) => r.posts > 0)) return null
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted">
          Sentiment (line) and post volume (bars){range === '7d' ? ' · Reddit, forums, HN' : ' · daily readings'}
        </span>
        {hasHistory && (
          <div className="flex gap-1 text-xs">
            {(['7d', '30d'] as const).map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRange(r)}
                className={cx('rounded px-1.5 py-0.5', range === r ? 'bg-raised text-fg' : 'text-faint hover:text-fg')}
              >
                {r}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 6, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--color-line)" />
            <XAxis
              dataKey="day"
              tickFormatter={(d: string) => d.slice(5)}
              tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis yAxisId="s" domain={[-100, 100]} ticks={[-100, -50, 0, 50, 100]} width={34} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis yAxisId="p" orientation="right" hide />
            <ReferenceLine yAxisId="s" y={0} stroke="var(--color-line-strong)" />
            <Tooltip
              cursor={{ fill: 'var(--color-raised)' }}
              contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
              formatter={(v, name) => (name === 'score' ? [v == null ? '—' : signedScore(Number(v)), 'Sentiment'] : [v, 'Posts'])}
            />
            <Bar yAxisId="p" dataKey="posts" fill="var(--color-accent)" fillOpacity={0.25} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            <Line yAxisId="s" dataKey="score" stroke="var(--color-accent)" strokeWidth={2} dot={{ r: 2.5 }} connectNulls isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function SourceChips({ sources }: { sources: SocialSourceStatus[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {sources
        .filter((s) => s.status !== 'skipped')
        .map((s) => (
          <span
            key={s.source}
            title={s.message ?? (s.via ? `via ${s.via}` : undefined)}
            className={cx(
              'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs',
              s.status === 'ok' ? 'border-line text-fg' : 'border-dashed border-line text-faint',
            )}
          >
            <span
              className={cx(
                'h-1.5 w-1.5 rounded-full',
                s.status === 'ok' ? 'bg-up' : s.status === 'empty' ? 'bg-faint' : 'bg-warn',
              )}
            />
            {s.label}
            {s.status === 'ok' ? <span className="tabular text-muted">{s.posts}</span> : <span>· {STATUS_NOTE[s.status]}</span>}
          </span>
        ))}
    </div>
  )
}

function PostRow({ post }: { post: SocialPost }) {
  return (
    <li className="flex gap-3 py-3">
      <span className={cx('tabular mt-0.5 w-9 shrink-0 text-end text-xs font-semibold', TONE_TEXT[post.tone])}>
        {signedScore(post.sentiment)}
      </span>
      <div className="min-w-0 flex-1">
        <a href={post.url} target="_blank" rel="noopener noreferrer" className="line-clamp-2 text-sm font-medium hover:text-accent-fg hover:underline">
          {post.title}
        </a>
        {post.excerpt && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{post.excerpt}</p>}
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-faint">
          <span>{post.community}</span>
          {post.score > 0 && <span className="tabular">▲ {compact(post.score)}</span>}
          {post.comments > 0 && <span className="tabular">{compact(post.comments)} comments</span>}
          <span>{relativeTime(post.created_at)}</span>
          {post.label && <Badge tone={post.label === 'bullish' ? 'up' : 'down'}>{post.label} tag</Badge>}
        </div>
      </div>
    </li>
  )
}

/** What retail investors are saying on Reddit, StockTwits, ValuePickr and
 * Hacker News: a -100..100 score, the bull/bear split, buzz, themes, the
 * most-engaged posts, and an optional AI digest. */
export default function SocialSentimentCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<SocialSentiment | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [summary, setSummary] = useState<{ data?: SocialSummary; error?: string; loading?: boolean }>({})
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    setSummary({})
    setShowAll(false)
    getSocialSentiment(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  function refresh() {
    setRefreshing(true)
    getSocialSentiment(symbol, market, true)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setRefreshing(false))
  }

  function runSummary() {
    setSummary({ loading: true })
    getSocialSummary(symbol, market)
      .then((d) => setSummary({ data: d }))
      .catch((err) => setSummary({ error: errorMessage(err) }))
  }

  const s = summary.data
  const posts = data ? (showAll ? data.top_posts : data.top_posts.slice(0, 6)) : []

  return (
    <Card id="section-social" section="Social sentiment">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Social sentiment
            {data?.mood && (
              <Badge tone={MOOD_TONE[data.mood]}>
                {data.mood} {signedScore(data.score)}
              </Badge>
            )}
          </span>
        }
        description={
          data
            ? `${data.posts} posts · last ${data.window_days} days · updated ${relativeTime(data.fetched_at)}`
            : 'What people are saying on Reddit, StockTwits and investor forums'
        }
        icon="chat"
        actions={
          data && (
            <Button size="sm" variant="ghost" icon="refresh" loading={refreshing} onClick={refresh}>
              Refresh
            </Button>
          )
        }
      />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-sm text-muted">Social sentiment unavailable: {error}</p>
        ) : !data ? (
          <div className="space-y-3">
            <div className="grid gap-4 sm:grid-cols-3">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
            <Skeleton className="h-32 w-full" />
            <p className="text-xs text-faint">Reading Reddit, StockTwits and forums - the first load can take up to a minute.</p>
          </div>
        ) : data.posts === 0 ? (
          <div className="space-y-3">
            <p className="text-sm text-muted">No recent posts about {data.query.name || data.symbol} found in the last {data.window_days} days.</p>
            <SourceChips sources={data.sources} />
          </div>
        ) : (
          <>
            {/* ------------------------------------------ headline numbers */}
            <div className="grid gap-5 sm:grid-cols-3">
              <Metric
                label="Sentiment score"
                value={
                  <span className={scoreClass(data.score)}>
                    {signedScore(data.score)}
                    <span className="ms-1 text-xs font-normal text-faint">/ 100</span>
                  </span>
                }
                meter={<ScoreScale score={data.score} />}
                caption={`${data.confidence} confidence · weighted by engagement and recency`}
              />
              <Metric
                label={
                  <>
                    Post mood <span className="text-faint">({data.posts})</span>
                  </>
                }
                value={(() => {
                  const top = MOOD_ORDER.reduce((a, b) => (data.counts[b] > data.counts[a] ? b : a))
                  return (
                    <span className={TONE_TEXT[top]}>
                      {Math.round((data.counts[top] / data.posts) * 100)}%
                      <span className="ms-1 text-xs font-normal text-faint">{top}</span>
                    </span>
                  )
                })()}
                meter={<SplitBar counts={data.counts} total={data.posts} />}
                caption={MOOD_ORDER.map((t) => (
                  <span key={t} className="me-2">
                    <span className={cx('tabular font-medium', TONE_TEXT[t])}>{Math.round((data.counts[t] / data.posts) * 100)}%</span> {t}
                  </span>
                ))}
              />
              <Metric
                label="Buzz (last 24h)"
                value={
                  data.buzz ? (
                    <span className={data.buzz.ratio >= 2 ? 'text-warn' : 'text-fg'}>{data.buzz.ratio.toFixed(1)}×</span>
                  ) : (
                    <span className="text-faint">—</span>
                  )
                }
                meter={<BuzzBar ratio={data.buzz?.ratio ?? null} />}
                caption={
                  data.buzz ? `${data.buzz.last_24h} posts vs ${data.buzz.daily_avg}/day average` : 'Too few posts to compare'
                }
              />
            </div>

            <TrendChart data={data} />

            {/* ------------------------------------------ sources + themes */}
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <div className="mb-2 text-xs font-medium text-muted">Sources</div>
                <SourceChips sources={data.sources} />
                {data.by_source.length > 1 && (
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {data.by_source.map((b) => (
                      <span key={b.source} className="text-muted">
                        {b.label} <span className={cx('tabular font-semibold', scoreClass(b.score))}>{signedScore(b.score)}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {data.themes.length > 0 && (
                <div>
                  <div className="mb-2 text-xs font-medium text-muted">What people talk about</div>
                  <div className="flex flex-wrap gap-1.5">
                    {data.themes.map((t) => (
                      <span
                        key={t.theme}
                        title={`${t.posts} posts, sentiment ${signedScore(t.score)}`}
                        className="inline-flex items-center gap-1.5 rounded-full bg-raised px-2.5 py-1 text-xs"
                      >
                        <span className={cx('h-1.5 w-1.5 rounded-full', TONE_BG[t.tone])} />
                        {t.theme}
                        <span className="tabular text-faint">{t.posts}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* ------------------------------------------ AI digest */}
            {s ? (
              <div className="space-y-4 rounded-lg bg-canvas p-4">
                <div>
                  <div className="mb-1 flex items-center gap-2 text-xs font-medium text-accent-fg">
                    AI digest <Badge tone={HYPE_TONE[s.hype_risk]}>hype risk {s.hype_risk}</Badge>
                  </div>
                  <p className="text-sm leading-relaxed text-fg/90">{s.summary}</p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {s.bull_points.length > 0 && (
                    <div>
                      <div className="mb-1.5 text-xs font-semibold tracking-wide text-up uppercase">Bulls say</div>
                      <ul className="space-y-1 text-sm">
                        {s.bull_points.map((p) => (
                          <li key={p} className="flex gap-2"><span className="text-up">+</span><span>{p}</span></li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {s.bear_points.length > 0 && (
                    <div>
                      <div className="mb-1.5 text-xs font-semibold tracking-wide text-down uppercase">Bears say</div>
                      <ul className="space-y-1 text-sm">
                        {s.bear_points.map((p) => (
                          <li key={p} className="flex gap-2"><span className="text-down">−</span><span>{p}</span></li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
                {s.hype_reason && <p className="border-t border-line pt-3 text-xs text-muted">{s.hype_reason}</p>}
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" variant="secondary" icon="cpu" loading={summary.loading} onClick={runSummary}>
                  {summary.loading ? 'Reading the chatter…' : 'AI digest'}
                </Button>
                <span className="text-[12px] text-faint">Summary, bull and bear arguments, and hype risk from your configured AI model.</span>
              </div>
            )}
            {summary.error && (
              <Alert title="AI digest failed" onDismiss={() => setSummary({})}>
                {summary.error}
              </Alert>
            )}

            {/* ------------------------------------------ top posts */}
            <div>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium text-muted">Most-engaged posts</span>
                {data.top_posts.length > 6 && (
                  <button type="button" onClick={() => setShowAll((v) => !v)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-fg">
                    {showAll ? 'Show fewer' : `Show all ${data.top_posts.length}`}
                    <Icon name="chevron" className={cx('h-3 w-3 transition-transform', showAll ? '-rotate-90' : 'rotate-90')} />
                  </button>
                )}
              </div>
              <ul className="divide-y divide-line">
                {posts.map((p) => (
                  <PostRow key={p.id} post={p} />
                ))}
              </ul>
            </div>

            <p className="text-[12px] text-faint">
              Public posts scored by keyword analysis. This is retail chatter, not investment advice. Posts can be wrong,
              promotional or coordinated.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
