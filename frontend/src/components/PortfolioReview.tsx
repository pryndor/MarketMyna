import { useEffect, useState, type FormEvent } from 'react'
import {
  getPortfolioReview,
  getPortfolioReviewAi,
  setReviewLimits,
  type PortfolioReview as Review,
  type PortfolioReviewAi,
  type ReviewFinding,
  type ReviewLimits,
  type ReviewSeverity,
} from '../api/portfolio'
import { cx } from '../lib/cx'
import { errorMessage } from '../lib/format'
import { toast } from '../lib/toast'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Icon, Input, Skeleton } from './ui'

const SEVERITY: Record<ReviewSeverity, { label: string; tone: 'down' | 'warn' | 'neutral'; dot: string }> = {
  high: { label: 'Act on this', tone: 'down', dot: 'bg-down' },
  medium: { label: 'Worth a look', tone: 'warn', dot: 'bg-warn' },
  low: { label: 'Minor', tone: 'neutral', dot: 'bg-faint' },
}

const SECTION_NAMES: Record<string, string> = {
  'section-holdings': 'Holdings',
  'section-analytics': 'Risk & analytics',
  'section-funds': 'Mutual funds',
  'section-fund-health': 'Fund health check',
  'section-transactions': 'Transactions',
}

const LIMIT_FIELDS: Array<{ key: keyof ReviewLimits; label: string; hint: string; suffix: string }> = [
  { key: 'max_holding', label: 'Max per holding', hint: 'Flag any single holding above this share', suffix: '%' },
  { key: 'max_sector', label: 'Max per sector', hint: 'Flag a sector above this share of stocks', suffix: '%' },
  { key: 'max_cash', label: 'Max cash', hint: 'Flag idle cash above this share', suffix: '%' },
  { key: 'loss_review', label: 'Review losses at', hint: 'Flag holdings this far below cost', suffix: '% down' },
  { key: 'min_holdings', label: 'Min holdings', hint: 'Flag a stock-only portfolio with fewer', suffix: 'stocks' },
]

const VISIBLE = 4

/** Analyst-style review of the current mix: what could be changed, why it
 * matters and the levers for it, checked against the user's own limits. */
export default function PortfolioReview({ portfolio, version }: { portfolio: string; version: string }) {
  const [data, setData] = useState<Review | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [nonce, setNonce] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [editing, setEditing] = useState(false)
  const [ai, setAi] = useState<{ data?: PortfolioReviewAi; error?: string; loading?: boolean }>({})

  useEffect(() => {
    let cancelled = false
    setError(null)
    setLoading(true)
    getPortfolioReview(portfolio)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [portfolio, version, nonce])

  useEffect(() => setAi({}), [portfolio, version])

  const runAi = () => {
    setAi({ loading: true })
    getPortfolioReviewAi(portfolio)
      .then((d) => setAi({ data: d }))
      .catch((err) => setAi({ error: errorMessage(err) }))
  }

  const findings = data?.findings ?? []
  const shown = showAll ? findings : findings.slice(0, VISIBLE)
  const tone = data?.grade === 'Good' ? 'text-up' : data?.grade === 'Fair' ? 'text-warn' : 'text-down'

  return (
    <Card id="section-review" section="Portfolio review">
      <CardHeader
        title="Portfolio review"
        icon="shield"
        description="What could be changed, why it matters and how - checked against your own limits"
        actions={
          <>
            <Button variant="ghost" size="sm" icon="settings" onClick={() => setEditing((v) => !v)} disabled={!data}>
              Your limits
            </Button>
            <Button variant="ghost" size="sm" icon="refresh" loading={loading && !!data} onClick={() => setNonce((n) => n + 1)}>
              Recheck
            </Button>
          </>
        }
      />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-sm text-down">{error}</p>
        ) : !data ? (
          <Skeleton className="h-40 w-full" />
        ) : data.score == null ? (
          <p className="text-sm text-muted">{data.summary}</p>
        ) : (
          <>
            {editing && (
              <LimitsForm
                portfolio={portfolio}
                limits={data.limits}
                onSaved={() => {
                  setEditing(false)
                  setNonce((n) => n + 1)
                }}
                onCancel={() => setEditing(false)}
              />
            )}

            <div className="flex flex-wrap items-end justify-between gap-4">
              <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
                <div>
                  <div className="text-xs text-faint">Score</div>
                  <div className="tabular text-2xl font-semibold">
                    {data.score}
                    <span className="text-sm text-faint">/100</span> <span className={cx('text-sm', tone)}>{data.grade}</span>
                  </div>
                </div>
                <div>
                  <div className="text-xs text-faint">Found</div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {(['high', 'medium', 'low'] as const).map((s) => {
                      const n = findings.filter((f) => f.severity === s).length
                      return n ? (
                        <Badge key={s} tone={SEVERITY[s].tone}>
                          {n} {SEVERITY[s].label}
                        </Badge>
                      ) : null
                    })}
                    {!findings.length && <span className="text-sm text-up">{data.summary}</span>}
                  </div>
                </div>
              </div>
              <Button size="sm" variant="secondary" icon="cpu" loading={ai.loading} onClick={runAi}>
                {ai.loading ? 'Reviewing…' : 'AI analyst summary'}
              </Button>
            </div>

            {ai.error && (
              <Alert title="AI summary failed" onDismiss={() => setAi({})}>
                {ai.error}
              </Alert>
            )}
            {ai.data && <AiBox ai={ai.data} onClose={() => setAi({})} />}

            {findings.length > 0 && (
              <ol className="space-y-3">
                {shown.map((f, i) => (
                  <FindingItem key={f.id} finding={f} index={i + 1} />
                ))}
              </ol>
            )}
            {findings.length > VISIBLE && (
              <button type="button" onClick={() => setShowAll((v) => !v)} className="text-xs font-medium text-accent-fg hover:text-fg">
                {showAll ? 'Show fewer' : `Show ${findings.length - VISIBLE} more`}
              </button>
            )}

            {data.good.length > 0 && (
              <div>
                <div className="mb-1.5 text-xs font-medium text-muted">What's working</div>
                <ul className="space-y-1">
                  {data.good.map((g) => (
                    <li key={g} className="flex items-start gap-2 text-sm">
                      <Icon name="check" className="mt-0.5 h-4 w-4 shrink-0 text-up" />
                      <span>{g}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-[12px] text-faint">
              Facts and general options checked against your own limits. Not investment advice; consider your goals and a
              registered adviser for decisions.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}

function FindingItem({ finding: f, index }: { finding: ReviewFinding; index: number }) {
  const sev = SEVERITY[f.severity]
  return (
    <li className="rounded-lg border border-line bg-canvas">
      <div className="flex items-start gap-3 px-4 pt-3">
        <span className="tabular mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-raised text-[11px] font-semibold text-muted">
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{f.title}</span>
            <Badge tone={sev.tone}>{sev.label}</Badge>
            {f.rule && <span className="text-xs text-faint">{f.rule}</span>}
          </div>
          <p className="mt-1 text-sm">{f.fact}</p>
        </div>
      </div>
      <div className="grid gap-3 px-4 py-3 ps-12 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium text-muted">Why it matters</div>
          <p className="text-sm text-fg/80">{f.why}</p>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-muted">What you can change</div>
          <ul className="space-y-1">
            {f.levers.map((l) => (
              <li key={l} className="flex gap-2 text-sm text-fg/90">
                <span className={cx('mt-2 h-1.5 w-1.5 shrink-0 rounded-full', sev.dot)} />
                <span>{l}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {SECTION_NAMES[f.section] && (
        <div className="border-t border-line px-4 py-2 ps-12">
          <button
            type="button"
            onClick={() => document.getElementById(f.section)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            className="text-xs text-muted hover:text-accent-fg"
          >
            See the numbers in {SECTION_NAMES[f.section]} →
          </button>
        </div>
      )}
    </li>
  )
}

function AiBox({ ai, onClose }: { ai: PortfolioReviewAi; onClose: () => void }) {
  return (
    <div className="rounded-lg border border-accent/40 bg-accent-soft px-4 py-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-accent-fg">AI analyst summary</span>
        <button type="button" onClick={onClose} className="text-muted hover:text-fg" aria-label="Close">
          <Icon name="x" />
        </button>
      </div>
      <p className="text-sm">{ai.summary}</p>
      {ai.priorities.length > 0 && (
        <>
          <div className="mt-3 mb-1 text-xs font-medium text-muted">Look into first</div>
          <ol className="list-decimal space-y-1 ps-5 text-sm">
            {ai.priorities.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ol>
        </>
      )}
      {ai.keep && (
        <p className="mt-3 text-sm">
          <span className="font-medium text-up">Fine as it is: </span>
          {ai.keep}
        </p>
      )}
    </div>
  )
}

function LimitsForm({
  portfolio,
  limits,
  onSaved,
  onCancel,
}: {
  portfolio: string
  limits: ReviewLimits
  onSaved: () => void
  onCancel: () => void
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(LIMIT_FIELDS.map((f) => [f.key, String(limits[f.key])])),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setReviewLimits(portfolio, Object.fromEntries(LIMIT_FIELDS.map((f) => [f.key, Number(values[f.key])])))
      .then(() => {
        toast.success('Limits saved')
        onSaved()
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setSaving(false))
  }

  return (
    <form onSubmit={save} className="space-y-3 rounded-lg border border-line bg-canvas p-4">
      <div className="text-xs text-muted">The review checks your portfolio against these. Set them to match how you invest.</div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {LIMIT_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} hint={`${f.hint} (${f.suffix})`}>
            <Input
              type="number"
              min="0"
              step="any"
              value={values[f.key]}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              className="w-full"
            />
          </Field>
        ))}
      </div>
      {error && <p className="text-sm text-down">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" loading={saving}>
          Save limits
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
