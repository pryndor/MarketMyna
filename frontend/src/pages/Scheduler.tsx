import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  getReportOptions,
  getSchedulerStatus,
  runSchedulerNow,
  updateSchedulerConfig,
  type ReportOptions,
  type RunNowResult,
  getRunSources,
  listReports,
  resolveRunTargets,
  type RunSource,
  type RunSourceCatalog,
  type SavedReportSummary,
  type ScheduleConfig,
  type SmartFile,
} from '../api/scheduler'
import { Link } from 'react-router-dom'
import ReportSettings from '../components/ReportSettings'
import { toast } from '../lib/toast'
import SymbolSearch from '../components/SymbolSearch'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Icon,
  Input,
  PageHeader,
  Segmented,
  Select,
  Skeleton,
  StatusDot,
  Switch,
  TagInput,
} from '../components/ui'
import { cx } from '../lib/cx'
import { errorMessage, relativeTime, serverTime } from '../lib/format'
import { MARKETS, MODES } from '../lib/options'
import { useSession } from '../lib/session'
import { useSection } from '../lib/section'

type Cadence = 'interval' | 'daily'

interface Draft {
  enabled: boolean
  cadence: Cadence
  interval: string
  time: string
  symbols: string[]
  market: string
  mode: string
  reportLanguage: string
  reportSections: string[]
  stockSections: Record<string, string[]>
  channelLanguages: Record<string, string>
  mfCodes: string[]
  ideasMarket: string
  ideasCategories: string[]
  ideasCount: number
  smartEnabled: boolean
  smartTopN: number
  smartAiTop: number
  smartEmailFull: boolean
  smartFile: SmartFile
  smartFileChannels: string[]
  reportBaseUrl: string
  sources: RunSource[]
  watchlistIds: number[]
  portfolioNames: string[]
}

export type ReportDraft = Pick<
  Draft,
  | 'reportLanguage'
  | 'reportSections'
  | 'stockSections'
  | 'channelLanguages'
  | 'symbols'
  | 'market'
  | 'mfCodes'
  | 'ideasMarket'
  | 'ideasCategories'
  | 'ideasCount'
  | 'smartEnabled'
  | 'smartTopN'
  | 'smartAiTop'
  | 'smartEmailFull'
  | 'smartFile'
  | 'smartFileChannels'
  | 'reportBaseUrl'
>

const CADENCES = [
  { value: 'daily', label: 'Daily at time' },
  { value: 'interval', label: 'Every N minutes' },
]

// Quick picks for a repeating report; any whole number of minutes works.
const INTERVAL_PRESETS = [15, 30, 60, 120, 240, 360]

function toDraft(cfg: ScheduleConfig): Draft {
  return {
    enabled: cfg.enabled,
    cadence: cfg.interval_minutes ? 'interval' : 'daily',
    interval: cfg.interval_minutes ? String(cfg.interval_minutes) : '60',
    time: cfg.time_of_day ?? '09:30',
    symbols: cfg.symbols,
    market: cfg.market,
    mode: cfg.mode,
    reportLanguage: cfg.report_language ?? 'en',
    reportSections: cfg.report_sections ?? [],
    stockSections: cfg.stock_sections ?? {},
    channelLanguages: cfg.channel_languages ?? {},
    mfCodes: cfg.mf_codes ?? [],
    ideasMarket: cfg.ideas_market ?? cfg.market,
    ideasCategories: cfg.ideas_categories ?? [],
    ideasCount: cfg.ideas_count ?? 3,
    smartEnabled: cfg.smart_enabled ?? false,
    smartTopN: cfg.smart_top_n ?? 5,
    smartAiTop: cfg.smart_ai_top ?? 10,
    smartEmailFull: cfg.smart_email_full ?? true,
    smartFile: cfg.smart_file ?? 'pdf',
    smartFileChannels: cfg.smart_file_channels ?? ['email', 'telegram'],
    reportBaseUrl: cfg.report_base_url ?? '',
    sources: cfg.sources ?? ['custom'],
    watchlistIds: cfg.watchlist_ids ?? [],
    portfolioNames: cfg.portfolio_names ?? [],
  }
}

function toPayload(d: Draft): Partial<ScheduleConfig> {
  return {
    enabled: d.enabled,
    interval_minutes: d.cadence === 'interval' ? parseInt(d.interval, 10) : null,
    time_of_day: d.cadence === 'daily' ? d.time : null,
    symbols: d.symbols,
    market: d.market,
    mode: d.mode,
    report_language: d.reportLanguage,
    report_sections: d.reportSections,
    stock_sections: d.stockSections,
    channel_languages: d.channelLanguages,
    mf_codes: d.mfCodes,
    ideas_market: d.ideasMarket,
    ideas_categories: d.ideasCategories,
    ideas_count: d.ideasCount,
    smart_enabled: d.smartEnabled,
    smart_top_n: d.smartTopN,
    smart_ai_top: d.smartAiTop,
    smart_email_full: d.smartEmailFull,
    smart_file: d.smartFile,
    smart_file_channels: d.smartFileChannels,
    report_base_url: d.reportBaseUrl.trim(),
    sources: d.sources,
    watchlist_ids: d.watchlistIds,
    portfolio_names: d.portfolioNames,
  }
}

/** Mirrors RuntimeSchedulerService's due-check: interval counts from the
 * last run, daily fires at HH:MM in the account's own time zone. */
function nextRun(cfg: ScheduleConfig, stockCount: number, timezone?: string): string {
  if (!cfg.enabled) return 'Disabled'
  if (!stockCount) return 'Nothing to run'
  if (cfg.interval_minutes) {
    if (!cfg.last_run_at) return 'On next tick'
    const due = serverTime(cfg.last_run_at).getTime() + cfg.interval_minutes * 60_000
    return due <= Date.now() ? 'On next tick' : new Date(due).toLocaleString()
  }
  if (cfg.time_of_day) return `Daily at ${cfg.time_of_day}${timezone ? ` (${timezone.replace(/_/g, ' ')})` : ''}`
  return 'Not scheduled'
}

export default function SchedulerPage() {
  const section = useSection()
  const [cfg, setCfg] = useState<ScheduleConfig | null>(null)
  const [running, setRunning] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)
  const [runningNow, setRunningNow] = useState(false)
  const [runResult, setRunResult] = useState<RunNowResult | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [options, setOptions] = useState<ReportOptions | null>(null)
  const [catalog, setCatalog] = useState<RunSourceCatalog | null>(null)
  const timezone = useSession((s) => s.me?.timezone)

  async function load() {
    try {
      const status = await getSchedulerStatus()
      setCfg(status.schedule)
      setRunning(status.running)
      setDraft(toDraft(status.schedule))
      setLoadError(null)
    } catch (err) {
      setLoadError(errorMessage(err))
    }
  }

  useEffect(() => {
    load()
    getReportOptions()
      .then(setOptions)
      .catch(() => setOptions(null))
    getRunSources()
      .then(setCatalog)
      .catch(() => setCatalog({ watchlists: [], portfolios: [] }))
  }, [])

  const draftTargets = useMemo(() => (draft ? resolveRunTargets(draft, catalog) : []), [draft, catalog])
  const savedTargets = useMemo(() => (cfg ? resolveRunTargets(toDraft(cfg), catalog) : []), [cfg, catalog])

  const dirty = useMemo(
    () => cfg != null && draft != null && JSON.stringify(toPayload(draft)) !== JSON.stringify(toPayload(toDraft(cfg))),
    [cfg, draft],
  )

  const intervalValid =
    draft?.cadence !== 'interval' || (Number(draft.interval) >= 1 && Number.isInteger(Number(draft.interval)))
  const timeValid = draft?.cadence !== 'daily' || /^\d{2}:\d{2}$/.test(draft.time)
  const urlValid = !draft?.reportBaseUrl.trim() || /^https?:\/\/\S+$/.test(draft.reportBaseUrl.trim())
  const sourcesValid = (draft?.sources.length ?? 0) > 0
  const valid = intervalValid && timeValid && urlValid && sourcesValid

  function patch(p: Partial<Draft>) {
    setDraft((d) => (d ? { ...d, ...p } : d))
  }

  async function save() {
    if (!draft || !valid) return
    setSaving(true)
    try {
      const updated = await updateSchedulerConfig(toPayload(draft))
      setCfg(updated)
      setDraft(toDraft(updated))
      toast.success('Schedule saved')
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function runNow() {
    setRunningNow(true)
    setRunResult(null)
    try {
      const result = await runSchedulerNow()
      setRunResult(result)
      toast[result.status === 'ok' ? 'success' : 'info'](`Run finished: ${result.status}`)
      await load()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setRunningNow(false)
    }
  }

  if (loadError) return <Alert title="Could not load scheduler">{loadError}</Alert>
  if (!cfg || !draft) return <Skeleton className="h-96 w-full" />

  return (
    <div>
      <PageHeader
        title="Scheduler"
        description={
          section === 'trader'
            ? 'A trading brief on your watchlist before the open or after the close: trade levels, your alerts, hot stocks and the AI read, on the channels you choose. Live price alerts are set on the Trade page.'
            : 'Run the agent pipeline on your watchlists and portfolio automatically and send a report, in the language and detail you choose, to each notification channel.'
        }
        actions={
          <Button
            variant="secondary"
            icon="play"
            loading={runningNow}
            disabled={!savedTargets.length}
            onClick={runNow}
            title={savedTargets.length ? `Run the saved selection now (${savedTargets.length} stocks)` : 'Choose what to run and save first'}
          >
            {runningNow ? 'Running…' : 'Run now'}
          </Button>
        }
      />


      <div className="mb-6 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-4">
        <StatusTile label="Worker" value={running ? 'Running' : 'Stopped'} tone={running ? 'up' : 'down'} />
        <StatusTile label="Schedule" value={cfg.enabled ? 'Enabled' : 'Disabled'} tone={cfg.enabled ? 'up' : 'neutral'} />
        <StatusTile label="Next run" value={nextRun(cfg, savedTargets.length, timezone)} />
        <StatusTile
          label="Last run"
          value={relativeTime(cfg.last_run_at)}
          tone={cfg.last_run_status == null ? undefined : cfg.last_run_status === 'ok' ? 'up' : 'warn'}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Configuration" icon="clock" />
          <CardBody className="space-y-6">
            <Switch
              checked={draft.enabled}
              onChange={(enabled) => patch({ enabled })}
              label="Automatic runs"
              description="When off, the watchlist only runs via Run now."
            />

            <div>
              <span className="mb-1.5 block text-xs font-medium text-muted">Cadence</span>
              <Segmented options={CADENCES} value={draft.cadence} onChange={(v) => patch({ cadence: v as Cadence })} size="sm" />
              <div className="mt-3">
                {draft.cadence === 'daily' ? (
                  <Field
                    label="Time of day (24-hour)"
                    hint={
                      <>
                        In your time zone, <b className="text-fg">{(timezone ?? '…').replace(/_/g, ' ')}</b> (
                        <Link to="/account" className="text-accent-fg hover:underline">
                          change
                        </Link>
                        ).
                      </>
                    }
                  >
                    <Input
                      type="time"
                      className="w-40"
                      value={draft.time}
                      onChange={(e) => patch({ time: e.target.value })}
                    />
                  </Field>
                ) : (
                  <Field
                    label="Interval (minutes)"
                    hint={!intervalValid ? <span className="text-down">A whole number of minutes, 1 or more</span> : undefined}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Input
                        type="number"
                        min={1}
                        step="1"
                        value={draft.interval}
                        onChange={(e) => patch({ interval: e.target.value })}
                        className="w-28"
                      />
                      {INTERVAL_PRESETS.map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={() => patch({ interval: String(m) })}
                          className={cx(
                            'rounded-md px-2 py-1 text-xs',
                            draft.interval === String(m) ? 'bg-accent-soft text-accent-fg' : 'bg-raised text-muted hover:text-fg',
                          )}
                        >
                          {m >= 60 ? `${m / 60}h` : `${m}m`}
                        </button>
                      ))}
                    </div>
                  </Field>
                )}
              </div>
            </div>

            <RunSources draft={draft} catalog={catalog} targets={draftTargets} onChange={patch} />

            <div>
              <span className="mb-1.5 block text-xs font-medium text-muted">Depth</span>
              <Segmented options={MODES} value={draft.mode} onChange={(mode) => patch({ mode })} size="sm" showHint />
            </div>
          </CardBody>
          <footer className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
            <span className="text-xs text-muted">{dirty ? 'Unsaved changes' : 'All changes saved'}</span>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" disabled={!dirty} onClick={() => setDraft(toDraft(cfg))}>
                Reset
              </Button>
              <Button size="sm" loading={saving} disabled={!dirty || !valid} onClick={save}>
                Save schedule
              </Button>
            </div>
          </footer>
        </Card>

        <div className="space-y-6 lg:col-span-2">
          <ReportSettings
            draft={{ ...draft, symbols: [...new Set(draftTargets.map((t) => t.symbol))] }}
            options={options}
            onChange={(p) => patch(p)}
            footer={
              <footer className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
                <span className="text-xs text-muted">{dirty ? 'Unsaved changes' : 'All changes saved'}</span>
                <Button size="sm" loading={saving} disabled={!dirty || !valid} onClick={save}>
                  Save schedule
                </Button>
              </footer>
            }
          />
        </div>

        <div className="space-y-6 lg:col-start-2 lg:row-start-1">
          {runResult && (
            <Card>
              <CardHeader
                title="Manual run"
                description={runResult.summary}
                actions={
                  <div className="flex items-center gap-2">
                    {runResult.report_token && (
                      <Link to={`/r/${runResult.report_token}`} className="text-xs text-accent-fg hover:underline">
                        Full report
                      </Link>
                    )}
                    <RunBadge status={runResult.status} />
                  </div>
                }
              />
              <ul className="divide-y divide-line">
                {runResult.results.map((r) => (
                  <li key={r.symbol} className="flex items-start gap-3 px-5 py-3 text-sm">
                    <span className={cx('mt-0.5', r.ok ? 'text-up' : 'text-down')}>
                      <Icon name={r.ok ? 'check' : 'x'} />
                    </span>
                    <span className="font-mono font-medium">{r.symbol}</span>
                    {r.error && <span className="min-w-0 break-words text-xs text-down">{r.error}</span>}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <RecentReports refreshKey={cfg.last_run_at} />

          <Card>
            <CardHeader
              title="Last run output"
              description={cfg.last_run_at ? serverTime(cfg.last_run_at).toLocaleString() : 'No runs yet'}
              actions={cfg.last_run_status ? <RunBadge status={cfg.last_run_status} /> : undefined}
            />
            <CardBody>
              {cfg.last_run_summary ? (
                <pre className="max-h-96 overflow-auto rounded-lg bg-canvas p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap text-fg/90">
                  {cfg.last_run_summary}
                </pre>
              ) : (
                <p className="text-xs text-muted">Output from the most recent scheduled or manual run appears here.</p>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  )
}

/** "What to run": saved watchlists, portfolio holdings and/or a custom
 * symbol list, in any combination. */
function RunSources({
  draft,
  catalog,
  targets,
  onChange,
}: {
  draft: Draft
  catalog: RunSourceCatalog | null
  targets: Array<{ symbol: string; market: string }>
  onChange: (p: Partial<Draft>) => void
}) {
  const toggle = (s: RunSource) =>
    onChange({ sources: draft.sources.includes(s) ? draft.sources.filter((x) => x !== s) : [...draft.sources, s] })
  const watchlists = catalog?.watchlists ?? []
  const portfolios = catalog?.portfolios ?? []
  const count = <T,>(items: T[], picked: (t: T) => boolean, size: (t: T) => number) =>
    items.filter(picked).reduce((n, t) => n + size(t), 0)
  const wlCount = count(watchlists, (w) => !draft.watchlistIds.length || draft.watchlistIds.includes(w.id), (w) => w.symbols.length)
  const pfCount = count(portfolios, (p) => !draft.portfolioNames.length || draft.portfolioNames.includes(p.name), (p) => p.symbols.length)

  const chip = (on: boolean, label: string, onClick: () => void, key: string) => (
    <button
      key={key}
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cx(
        'rounded-full border px-2.5 py-0.5 text-xs font-medium',
        on ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:text-fg',
      )}
    >
      {label}
    </button>
  )

  const option = (source: RunSource, title: string, detail: string, body?: ReactNode) => {
    const on = draft.sources.includes(source)
    return (
      <div className={cx('rounded-lg border px-3 py-2.5', on ? 'border-accent/60 bg-accent-soft/40' : 'border-line')}>
        <label className="flex cursor-pointer items-start gap-3">
          <input type="checkbox" checked={on} onChange={() => toggle(source)} className="mt-0.5 h-4 w-4 accent-[var(--color-accent)]" />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium">{title}</span>
            <span className="block text-xs text-muted">{detail}</span>
          </span>
        </label>
        {on && body && <div className="mt-2.5 ps-7">{body}</div>}
      </div>
    )
  }

  return (
    <div>
      <span className="mb-1.5 block text-xs font-medium text-muted">What to run</span>
      <div className="space-y-2">
        {option(
          'watchlist',
          'Watchlists',
          catalog == null ? 'Loading…' : watchlists.length ? `${wlCount} stocks` : 'No watchlists yet',
          watchlists.length > 1 ? (
            <div className="flex flex-wrap gap-1.5">
              {chip(!draft.watchlistIds.length, 'All', () => onChange({ watchlistIds: [] }), 'all')}
              {watchlists.map((w) =>
                chip(
                  draft.watchlistIds.includes(w.id),
                  `${w.name} · ${w.symbols.length}`,
                  () =>
                    onChange({
                      watchlistIds: draft.watchlistIds.includes(w.id)
                        ? draft.watchlistIds.filter((id) => id !== w.id)
                        : [...draft.watchlistIds, w.id],
                    }),
                  String(w.id),
                ),
              )}
            </div>
          ) : watchlists.length === 1 && !wlCount ? (
            <p className="text-xs text-muted">
              Your watchlist is empty. Add stocks on the{' '}
              <Link to="/watchlist" className="text-accent-fg hover:underline">
                Watchlist
              </Link>{' '}
              page.
            </p>
          ) : undefined,
        )}
        {option(
          'portfolio',
          'Portfolio holdings',
          catalog == null ? 'Loading…' : portfolios.length ? `${pfCount} stocks you own` : 'No portfolio yet',
          portfolios.length > 1 ? (
            <div className="flex flex-wrap gap-1.5">
              {chip(!draft.portfolioNames.length, 'All', () => onChange({ portfolioNames: [] }), 'all')}
              {portfolios.map((p) =>
                chip(
                  draft.portfolioNames.includes(p.name),
                  `${p.name} · ${p.symbols.length}`,
                  () =>
                    onChange({
                      portfolioNames: draft.portfolioNames.includes(p.name)
                        ? draft.portfolioNames.filter((n) => n !== p.name)
                        : [...draft.portfolioNames, p.name],
                    }),
                  p.name,
                ),
              )}
            </div>
          ) : undefined,
        )}
        {option(
          'custom',
          'Custom symbols',
          draft.symbols.length ? `${draft.symbols.length} symbols listed here` : 'Type symbols just for this schedule',
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-[140px_minmax(0,1fr)]">
              <Field label="Market">
                <Select options={MARKETS} value={draft.market} onChange={(e) => onChange({ market: e.target.value })} />
              </Field>
              <Field label="Symbols" hint="Enter or comma to add · Backspace removes the last">
                <TagInput values={draft.symbols} onChange={(symbols) => onChange({ symbols })} placeholder="AAPL, MSFT, NVDA" />
              </Field>
            </div>
            <WatchlistSearch
              market={draft.market}
              onAdd={(sym) => !draft.symbols.includes(sym) && onChange({ symbols: [...draft.symbols, sym] })}
            />
          </div>,
        )}
      </div>
      <p className={cx('mt-2 text-xs', draft.sources.length && targets.length ? 'text-muted' : 'text-warn')}>
        {!draft.sources.length
          ? 'Choose at least one source.'
          : targets.length
            ? `Each run covers ${targets.length} stock${targets.length === 1 ? '' : 's'}${
                draft.sources.length > 1 ? ' (duplicates counted once)' : ''
              }: ${targets
                .slice(0, 12)
                .map((t) => t.symbol)
                .join(', ')}${targets.length > 12 ? ', …' : ''}`
            : 'The chosen sources have no stocks yet.'}
      </p>
    </div>
  )
}

/** Full smart reports saved by past runs; hidden until the first one exists. */
function RecentReports({ refreshKey }: { refreshKey: string | null }) {
  const [reports, setReports] = useState<SavedReportSummary[]>([])
  useEffect(() => {
    listReports(8)
      .then(setReports)
      .catch(() => setReports([]))
  }, [refreshKey])
  if (!reports.length) return null
  return (
    <Card>
      <CardHeader title="Full reports" description="Every monitored stock with levels and a 1-week range (Smart messaging runs)." />
      <ul className="divide-y divide-line">
        {reports.map((r) => (
          <li key={r.token}>
            <Link to={`/r/${r.token}`} className="flex items-center gap-3 px-5 py-2.5 text-sm hover:bg-raised">
              <span className="min-w-0 flex-1 truncate">{r.title}</span>
              <span className="text-xs text-muted">{relativeTime(r.created_at)}</span>
              <Icon name="chevron" className="h-3.5 w-3.5 text-faint" />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function RunBadge({ status }: { status: string }) {
  const tone = status === 'ok' ? 'up' : status === 'failed' ? 'down' : 'warn'
  return <Badge tone={tone}>{status.replace(/_/g, ' ')}</Badge>
}

function StatusTile({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'down' | 'warn' | 'neutral' }) {
  return (
    <div className="bg-surface px-5 py-4">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 flex items-center gap-2 text-sm font-semibold">
        {tone && <StatusDot tone={tone} />}
        <span className="truncate">{value}</span>
      </div>
    </div>
  )
}

/** Adds symbols from the full market listing, scoped to the schedule's market. */
function WatchlistSearch({ market, onAdd }: { market: string; onAdd: (symbol: string) => void }) {
  const [text, setText] = useState('')
  return (
    <SymbolSearch
      value={text}
      onChange={setText}
      onSelect={(row) => {
        onAdd(row.symbol)
        setText('')
      }}
      market={market}
      exclude={['mf']}
      placeholder={`Search ${market === 'global' ? 'all markets' : 'the ' + market.replace('_', ' ') + ' market'} to add symbols`}
    />
  )
}
