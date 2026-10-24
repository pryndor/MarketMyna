import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { getRunSources, type RunSourceCatalog } from '../../api/scheduler'
import {
  deleteSavedScan,
  getScanCatalog,
  listSavedScans,
  runScan,
  saveScan,
  updateSavedScan,
  type SavedScan,
  type ScanInfo,
  type ScanRequest,
  type ScanResult,
  type Universe,
} from '../../api/trade'
import ExportMenu from '../ExportMenu'
import { cx } from '../../lib/cx'
import { errorMessage, num, pct, price as fmtPrice, relativeTime } from '../../lib/format'
import { MARKETS } from '../../lib/options'
import { toast } from '../../lib/toast'
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Field, Icon, Input, Segmented, Select, Switch, TagInput } from '../ui'
import { CURRENCY } from './shared'

const PRESETS: Array<{ name: string; scans: string[]; match: 'any' | 'all' }> = [
  { name: 'Breakouts', scans: ['high_52w', 'breakout_20d', 'volume_surge'], match: 'any' },
  { name: 'Momentum', scans: ['ema_cross_up', 'supertrend_buy', 'uptrend'], match: 'any' },
  { name: 'Oversold bounce', scans: ['rsi_oversold', 'near_support', 'open_low'], match: 'any' },
  { name: 'Gappers', scans: ['gap_up', 'gap_down', 'big_mover'], match: 'any' },
  { name: 'Intraday ORB', scans: ['orb_up', 'orb_down', 'vwap_cross_up', 'vwap_cross_down'], match: 'any' },
  { name: 'Coiled (NR7 inside day)', scans: ['nr7', 'inside_day'], match: 'all' },
]

const BEARISH = new Set([
  'gap_down', 'low_52w', 'breakdown_20d', 'rsi_overbought', 'ema_cross_down', 'supertrend_sell', 'open_high', 'orb_down', 'vwap_cross_down',
])
const NEUTRAL = new Set(['big_mover', 'volume_surge', 'inside_day', 'nr7'])

const TOP_N = [50, 100, 200, 500].map((n) => ({ value: String(n), label: `Top ${n}` }))

export default function ScannerTab({ market, onOpen }: { market: string; onOpen: (symbol: string, market: string) => void }) {
  const [catalog, setCatalog] = useState<ScanInfo[]>([])
  const [sources, setSources] = useState<RunSourceCatalog | null>(null)
  const [saved, setSaved] = useState<SavedScan[]>([])
  const [req, setReq] = useState<ScanRequest>({
    universe: { sources: ['top'], market: market === 'global' ? 'us' : market, top_n: 100, watchlist_ids: [], portfolio_names: [], symbols: [] },
    scans: PRESETS[0].scans,
    params: {},
    match: 'any',
  })
  const [result, setResult] = useState<ScanResult | null>(null)
  const [running, setRunning] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveNotify, setSaveNotify] = useState(true)
  const [saveEvery, setSaveEvery] = useState('15')
  const [filter, setFilter] = useState('')

  useEffect(() => {
    getScanCatalog().then(setCatalog).catch(() => setCatalog([]))
    getRunSources().then(setSources).catch(() => setSources({ watchlists: [], portfolios: [] }))
    loadSaved()
  }, [])

  function loadSaved() {
    listSavedScans()
      .then(setSaved)
      .catch(() => setSaved([]))
  }

  const byId = useMemo(() => Object.fromEntries(catalog.map((c) => [c.id, c])), [catalog])
  const groups = useMemo(() => {
    const g: Record<string, ScanInfo[]> = {}
    catalog.forEach((c) => (g[c.group] ??= []).push(c))
    return Object.entries(g)
  }, [catalog])

  const setUniverse = (patch: Partial<Universe>) => setReq((r) => ({ ...r, universe: { ...r.universe, ...patch } }))
  const toggleSource = (s: Universe['sources'][number]) =>
    setUniverse({ sources: req.universe.sources.includes(s) ? req.universe.sources.filter((x) => x !== s) : [...req.universe.sources, s] })
  const toggleScan = (id: string) =>
    setReq((r) => ({ ...r, scans: r.scans.includes(id) ? r.scans.filter((x) => x !== id) : [...r.scans, id] }))

  async function run() {
    setRunning(true)
    setResult(null)
    try {
      const r = await runScan(req)
      setResult(r)
      if (r.failed.length) toast.info(`${r.failed.length} symbol(s) had no data`)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setRunning(false)
    }
  }

  async function save() {
    if (!saveName.trim()) return
    try {
      await saveScan({ ...req, name: saveName.trim(), notify: saveNotify, interval_minutes: Math.max(5, parseInt(saveEvery, 10) || 15) })
      toast.success('Scan saved')
      setSaveName('')
      loadSaved()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const rows = (result?.rows ?? []).filter(
    (r) => !filter || r.symbol.toLowerCase().includes(filter.toLowerCase()) || (r.name ?? '').toLowerCase().includes(filter.toLowerCase()),
  )
  const universeEmpty = req.universe.sources.length === 0 || (req.universe.sources.length === 1 && req.universe.sources[0] === 'custom' && !req.universe.symbols.length)

  return (
    <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
      <div className="space-y-6">
        <Card>
          <CardHeader title="Scan" icon="search" />
          <CardBody className="space-y-5">
            <div>
              <span className="mb-1.5 block text-xs font-medium text-muted">Presets</span>
              <div className="flex flex-wrap gap-1.5">
                {PRESETS.map((p) => (
                  <button
                    key={p.name}
                    type="button"
                    onClick={() => setReq((r) => ({ ...r, scans: p.scans, match: p.match }))}
                    className="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted hover:border-line-strong hover:text-fg"
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <span className="block text-xs font-medium text-muted">Universe</span>
              <SourceRow on={req.universe.sources.includes('top')} onToggle={() => toggleSource('top')} title="Largest stocks">
                <div className="grid grid-cols-2 gap-2">
                  <Select
                    options={MARKETS.filter((m) => m.value !== 'global')}
                    value={req.universe.market}
                    onChange={(e) => setUniverse({ market: e.target.value })}
                  />
                  <Select options={TOP_N} value={String(req.universe.top_n)} onChange={(e) => setUniverse({ top_n: Number(e.target.value) })} />
                </div>
              </SourceRow>
              <SourceRow
                on={req.universe.sources.includes('watchlist')}
                onToggle={() => toggleSource('watchlist')}
                title={`Watchlists${sources ? ` · ${sources.watchlists.reduce((n, w) => n + w.symbols.length, 0)}` : ''}`}
              />
              <SourceRow
                on={req.universe.sources.includes('portfolio')}
                onToggle={() => toggleSource('portfolio')}
                title={`Portfolio holdings${sources ? ` · ${sources.portfolios.reduce((n, p) => n + p.symbols.length, 0)}` : ''}`}
              />
              <SourceRow on={req.universe.sources.includes('custom')} onToggle={() => toggleSource('custom')} title="Custom list">
                <TagInput values={req.universe.symbols} onChange={(symbols) => setUniverse({ symbols })} placeholder="Symbols in the market above" />
              </SourceRow>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted">Scans ({req.scans.length})</span>
                <Segmented
                  options={[
                    { value: 'any', label: 'Match any' },
                    { value: 'all', label: 'Match all' },
                  ]}
                  value={req.match}
                  onChange={(m) => setReq((r) => ({ ...r, match: m as 'any' | 'all' }))}
                  size="sm"
                />
              </div>
              {groups.map(([group, items]) => (
                <div key={group}>
                  <div className="mb-1 text-[12px] font-medium tracking-wide text-faint uppercase">{group}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {items.map((s) => {
                      const on = req.scans.includes(s.id)
                      return (
                        <button
                          key={s.id}
                          type="button"
                          aria-pressed={on}
                          onClick={() => toggleScan(s.id)}
                          className={cx(
                            'rounded-full border px-2.5 py-0.5 text-xs font-medium',
                            on ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:text-fg',
                          )}
                        >
                          {s.label}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
              {req.scans.some((id) => byId[id]?.param) && (
                <div className="grid grid-cols-2 gap-2 rounded-lg border border-line p-2.5">
                  {req.scans
                    .filter((id) => byId[id]?.param)
                    .map((id) => (
                      <label key={id} className="text-[12px] text-muted">
                        {byId[id].label} · {byId[id].param}
                        <Input
                          type="number"
                          step="any"
                          value={req.params[id] ?? byId[id].default ?? ''}
                          onChange={(e) =>
                            setReq((r) => ({ ...r, params: { ...r.params, [id]: parseFloat(e.target.value) } }))
                          }
                          className="mt-0.5"
                        />
                      </label>
                    ))}
                </div>
              )}
            </div>

            <Button onClick={run} loading={running} disabled={!req.scans.length || universeEmpty} icon="search" className="w-full">
              {running ? 'Scanning…' : 'Run scan'}
            </Button>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Save & get alerts" description="Runs every N minutes while the market is open and sends only new matches." />
          <CardBody className="space-y-3">
            <Input value={saveName} onChange={(e) => setSaveName(e.target.value)} placeholder="Name, e.g. Nifty 100 breakouts" />
            <div className="flex items-center justify-between gap-3">
              <Switch checked={saveNotify} onChange={setSaveNotify} label={<span className="text-sm">Notify me</span>} />
              <Field label="Every (min)" className="w-28">
                <Input type="number" min="5" value={saveEvery} onChange={(e) => setSaveEvery(e.target.value)} />
              </Field>
            </div>
            <Button size="sm" variant="secondary" onClick={save} disabled={!saveName.trim() || !req.scans.length}>
              Save scan
            </Button>
            {saved.length > 0 && (
              <ul className="divide-y divide-line rounded-lg border border-line">
                {saved.map((s) => (
                  <li key={s.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                    <button
                      type="button"
                      className="min-w-0 flex-1 truncate text-start hover:underline"
                      onClick={() => setReq({ universe: s.universe, scans: s.scans, params: s.params ?? {}, match: s.match })}
                      title="Load into the form"
                    >
                      {s.name}
                      <span className="block text-[12px] text-muted">
                        {s.last_run_at ? `${s.last_count ?? 0} matches · ${relativeTime(s.last_run_at)}` : 'not run yet'}
                        {s.notify && ` · every ${s.interval_minutes}m`}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => updateSavedScan(s.id, { notify: !s.notify }).then(loadSaved, (e) => toast.error(errorMessage(e)))}
                      className={cx('rounded-md p-1.5', s.notify ? 'text-accent-fg' : 'text-faint hover:text-fg')}
                      aria-label={s.notify ? 'Turn notifications off' : 'Turn notifications on'}
                      title={s.notify ? 'Notifications on' : 'Notifications off'}
                    >
                      <Icon name="bell" />
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteSavedScan(s.id).then(loadSaved)}
                      className="rounded-md p-1.5 text-faint hover:bg-down-soft hover:text-down"
                      aria-label={`Delete ${s.name}`}
                    >
                      <Icon name="trash" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHeader
          title="Results"
          description={
            result
              ? `${result.rows.length} match${result.rows.length === 1 ? '' : 'es'} out of ${result.scanned} stocks · ${result.seconds}s`
              : 'Pick a universe and scans, then run.'
          }
          actions={
            result && result.rows.length > 0 ? (
              <div className="flex items-center gap-2">
                {result.rows.length > 5 && <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter" className="w-36" />}
                <ExportMenu
                  title="Scan results"
                  subtitle={`${result.rows.length} matches of ${result.scanned}`}
                  tables={() => [{
                    title: 'Scan results',
                    columns: [
                      { key: 'symbol', label: 'Symbol' }, { key: 'name', label: 'Name' }, { key: 'market', label: 'Market' },
                      { key: 'price', label: 'Price', kind: 'number' }, { key: 'change_percent', label: 'Change %', kind: 'pct' },
                      { key: 'gap_percent', label: 'Gap %', kind: 'pct' }, { key: 'volume_ratio', label: 'Volume x avg', kind: 'number' },
                      { key: 'rsi', label: 'RSI', kind: 'number', digits: 1 }, { key: 'matched', label: 'Matched scans' },
                      { key: 'reasons', label: 'Why' },
                    ],
                    rows,
                  }]}
                />
              </div>
            ) : undefined
          }
        />
        {running ? (
          <CardBody>
            <p className="text-sm text-muted">Downloading bars and scanning… large universes take 10–30 seconds.</p>
          </CardBody>
        ) : !result ? (
          <EmptyState icon="search" title="No scan run yet" description="Daily bars include today's live bar; intraday scans use 5-minute bars." />
        ) : rows.length === 0 ? (
          <EmptyState icon="search" title="No matches" description="Try Match any, fewer scans or a bigger universe." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-y border-line text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 text-start font-medium">Stock</th>
                  <th className="px-3 py-2 text-end font-medium">Price</th>
                  <th className="px-3 py-2 text-end font-medium">Change</th>
                  <th className="px-3 py-2 text-end font-medium">Gap</th>
                  <th className="px-3 py-2 text-end font-medium">Vol ×</th>
                  <th className="px-3 py-2 text-end font-medium">RSI</th>
                  <th className="px-4 py-2 text-start font-medium">Signals</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((r) => (
                  <tr key={`${r.market}:${r.symbol}`} className="align-top hover:bg-raised/50">
                    <td className="px-4 py-2">
                      <button type="button" onClick={() => onOpen(r.symbol, r.market)} className="font-mono font-medium hover:underline">
                        {r.symbol}
                      </button>
                      {r.name && <div className="max-w-44 truncate text-xs text-muted">{r.name}</div>}
                    </td>
                    <td className="tabular px-3 py-2 text-end">{fmtPrice(r.price, CURRENCY[r.market])}</td>
                    <td className={cx('tabular px-3 py-2 text-end', r.change_percent >= 0 ? 'text-up' : 'text-down')}>{pct(r.change_percent)}</td>
                    <td className="tabular px-3 py-2 text-end text-xs">{pct(r.gap_percent, 1)}</td>
                    <td className="tabular px-3 py-2 text-end">{r.volume_ratio != null ? num(r.volume_ratio, 1) : '—'}</td>
                    <td className="tabular px-3 py-2 text-end">{num(r.rsi, 0)}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {r.matched.map((m, i) => (
                          <span key={m} title={r.reasons[i]}>
                            <Badge tone={BEARISH.has(m) ? 'down' : NEUTRAL.has(m) ? 'neutral' : 'up'}>
                              {byId[m]?.label ?? m}
                            </Badge>
                          </span>
                        ))}
                      </div>
                      <div className="mt-0.5 text-[12px] text-muted">{r.reasons.slice(0, 2).join(' · ')}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function SourceRow({ on, onToggle, title, children }: { on: boolean; onToggle: () => void; title: string; children?: ReactNode }) {
  return (
    <div className={cx('rounded-lg border px-3 py-2', on ? 'border-accent/60 bg-accent-soft/40' : 'border-line')}>
      <label className="flex cursor-pointer items-center gap-2.5 text-sm">
        <input type="checkbox" checked={on} onChange={onToggle} className="h-4 w-4 accent-[var(--color-accent)]" />
        {title}
      </label>
      {on && children && <div className="mt-2">{children}</div>}
    </div>
  )
}
