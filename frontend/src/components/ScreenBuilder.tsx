import { useEffect, useState } from 'react'
import { listScreenMetrics, type CustomScreen, type MetricGroup, type ScreenOp } from '../api/screens'
import { cx } from '../lib/cx'
import { Button, Icon, Input } from './ui'

const STORE_KEY = 'mm.customScreen'
const MAX_RULES = 12

const DEFAULT_SCREEN: CustomScreen = {
  rules: [
    { field: 'roe', op: '>', value: 15 },
    { field: 'pe', op: 'between', value: 0, value2: 25 },
    { field: 'debt_equity', op: '<', value: 1 },
  ],
  sectors: [],
  sort: 'roe',
  descending: true,
  columns: [],
  large_only: false,
}

const OPS: Array<{ value: ScreenOp; label: string }> = [
  { value: '>', label: 'above' },
  { value: '<', label: 'below' },
  { value: 'between', label: 'between' },
  { value: 'top', label: 'in the top %' },
  { value: 'bottom', label: 'in the bottom %' },
  { value: 'below_sector', label: 'below sector median' },
  { value: 'above_sector', label: 'above sector median' },
]

const SELECT =
  'h-8 rounded-lg border border-line bg-canvas px-2 text-xs text-fg focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-soft'

/** The last screen this browser ran; the default when there is none. */
export function loadScreen(): CustomScreen {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) ?? 'null') as CustomScreen | null
    if (saved && Array.isArray(saved.rules) && saved.rules.length) return { ...DEFAULT_SCREEN, ...saved }
  } catch {
    // private window or bad JSON: start from the default
  }
  return DEFAULT_SCREEN
}

function storeScreen(spec: CustomScreen) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(spec))
  } catch {
    // storage blocked: the screen still runs, it just isn't remembered
  }
}

type Draft = { field: string; op: ScreenOp; value: string; value2: string }

const toDraft = (spec: CustomScreen): Draft[] =>
  spec.rules.map((r) => ({ field: r.field, op: r.op, value: r.value == null ? '' : String(r.value), value2: r.value2 == null ? '' : String(r.value2) }))

const num = (s: string): number | null => (s.trim() === '' || !Number.isFinite(Number(s)) ? null : Number(s))

function MetricSelect({ groups, value, onChange, className }: { groups: MetricGroup[]; value: string; onChange: (v: string) => void; className?: string }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={cx(SELECT, className)} aria-label="Metric">
      {groups.map((g) => (
        <optgroup key={g.group} label={g.group}>
          {g.metrics.map((m) => (
            <option key={m.key} value={m.key} title={m.hint}>
              {m.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

/** Own rules for Screens: metric + operator + value, sectors, sort, columns. */
export default function ScreenBuilder({
  spec,
  sectors,
  running,
  onRun,
}: {
  spec: CustomScreen
  /** Sectors seen in the last run of this market. */
  sectors: string[]
  running: boolean
  onRun: (spec: CustomScreen) => void
}) {
  const [groups, setGroups] = useState<MetricGroup[]>([])
  const [rules, setRules] = useState<Draft[]>(() => toDraft(spec))
  const [picked, setPicked] = useState<string[]>(spec.sectors)
  const [sort, setSort] = useState(spec.sort ?? '')
  const [descending, setDescending] = useState(spec.descending)
  const [columns, setColumns] = useState<string[]>(spec.columns)
  const [largeOnly, setLargeOnly] = useState(spec.large_only)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    listScreenMetrics().then(setGroups).catch(() => undefined)
  }, [])

  const label = (key: string) => groups.flatMap((g) => g.metrics).find((m) => m.key === key)?.label ?? key
  const hint = (key: string) => groups.flatMap((g) => g.metrics).find((m) => m.key === key)?.hint

  function patch(i: number, change: Partial<Draft>) {
    setRules((rs) => rs.map((r, j) => (j === i ? { ...r, ...change } : r)))
  }

  function run() {
    const out: CustomScreen['rules'] = []
    for (const r of rules) {
      const value = num(r.value)
      const sectorOp = r.op === 'below_sector' || r.op === 'above_sector'
      if (value == null && !sectorOp) return setProblem(`${label(r.field)}: enter a number`)
      if (r.op === 'between' && num(r.value2) == null) return setProblem(`${label(r.field)}: enter both ends of the range`)
      if ((r.op === 'top' || r.op === 'bottom') && !(value! > 0 && value! <= 100)) return setProblem(`${label(r.field)}: pick a percent from 1 to 100`)
      out.push({ field: r.field, op: r.op, value, ...(r.op === 'between' ? { value2: num(r.value2) } : {}) })
    }
    if (!out.length) return setProblem('Add at least one rule')
    setProblem(null)
    const next: CustomScreen = { rules: out, sectors: picked, sort: sort || out[0].field, descending, columns, large_only: largeOnly }
    storeScreen(next)
    onRun(next)
  }

  const sortOptions = [...new Set([...rules.map((r) => r.field), ...columns, 'market_cap', 'price'])]
  const sectorList = [...new Set([...sectors, ...picked])].sort()

  return (
    <div className="space-y-3 rounded-lg border border-line bg-canvas/40 p-3">
      <div className="space-y-2">
        {rules.map((r, i) => {
          const sectorOp = r.op === 'below_sector' || r.op === 'above_sector'
          const pctOp = r.op === 'top' || r.op === 'bottom'
          return (
            <div key={i} className="flex flex-wrap items-center gap-1.5">
              {groups.length ? (
                <MetricSelect groups={groups} value={r.field} onChange={(field) => patch(i, { field })} className="w-44" />
              ) : (
                <span className={cx(SELECT, 'inline-flex w-44 items-center text-muted')}>{r.field}</span>
              )}
              <select value={r.op} onChange={(e) => patch(i, { op: e.target.value as ScreenOp })} className={cx(SELECT, 'w-40')} aria-label="Operator">
                {OPS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              {sectorOp && <span className="text-xs text-faint">×</span>}
              <Input
                value={r.value}
                onChange={(e) => patch(i, { value: e.target.value })}
                onKeyDown={(e) => e.key === 'Enter' && run()}
                placeholder={sectorOp ? '1' : pctOp ? '10' : 'Value'}
                inputMode="decimal"
                className="h-8 w-20 text-xs"
                aria-label="Value"
              />
              {r.op === 'between' && (
                <>
                  <span className="text-xs text-faint">and</span>
                  <Input
                    value={r.value2}
                    onChange={(e) => patch(i, { value2: e.target.value })}
                    onKeyDown={(e) => e.key === 'Enter' && run()}
                    placeholder="Value"
                    inputMode="decimal"
                    className="h-8 w-20 text-xs"
                    aria-label="Upper value"
                  />
                </>
              )}
              {pctOp && <span className="text-xs text-faint">%</span>}
              <button
                type="button"
                onClick={() => setRules((rs) => rs.filter((_, j) => j !== i))}
                className="rounded p-1 text-faint hover:text-down"
                aria-label="Remove rule"
                title="Remove rule"
              >
                <Icon name="x" className="h-3.5 w-3.5" />
              </button>
              {hint(r.field) && <span className="hidden text-[11px] text-faint lg:inline">{hint(r.field)}</span>}
            </div>
          )
        })}
        {rules.length < MAX_RULES && (
          <button
            type="button"
            onClick={() => setRules((rs) => [...rs, { field: 'pe', op: '<', value: '', value2: '' }])}
            className="inline-flex items-center gap-1 text-xs text-accent-fg hover:underline"
          >
            + Add rule
          </button>
        )}
      </div>

      {sectorList.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted">
            Sectors <span className="font-normal text-faint">{picked.length ? `${picked.length} picked` : 'all'}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {sectorList.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={picked.includes(s)}
                onClick={() => setPicked((p) => (p.includes(s) ? p.filter((x) => x !== s) : [...p, s]))}
                className={cx(
                  'rounded-full border px-2.5 py-0.5 text-[11px]',
                  picked.includes(s) ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:border-line-strong hover:text-fg',
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        <label className="flex items-center gap-1.5 text-muted">
          Sort by
          <select value={sort || rules[0]?.field || ''} onChange={(e) => setSort(e.target.value)} className={SELECT}>
            {sortOptions.map((k) => (
              <option key={k} value={k}>
                {label(k)}
              </option>
            ))}
          </select>
          <select value={descending ? 'desc' : 'asc'} onChange={(e) => setDescending(e.target.value === 'desc')} className={SELECT} aria-label="Sort order">
            <option value="desc">high first</option>
            <option value="asc">low first</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-muted">
          Show also
          {groups.length > 0 && (
            <MetricSelect
              groups={[{ group: '', metrics: [{ key: '', label: 'add a column…', hint: '' }] }, ...groups]}
              value=""
              onChange={(k) => k && !columns.includes(k) && setColumns((c) => [...c, k])}
            />
          )}
        </label>
        {columns.map((c) => (
          <span key={c} className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] text-muted">
            {label(c)}
            <button type="button" onClick={() => setColumns((cs) => cs.filter((x) => x !== c))} aria-label={`Remove ${label(c)} column`} className="hover:text-down">
              <Icon name="x" className="h-3 w-3" />
            </button>
          </span>
        ))}
        <label className="flex items-center gap-1.5 text-muted">
          <input type="checkbox" checked={largeOnly} onChange={(e) => setLargeOnly(e.target.checked)} className="h-3.5 w-3.5 accent-[var(--color-accent)]" />
          Largest 100 only
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" icon="filter" loading={running} onClick={run}>
          Run screen
        </Button>
        {problem && <span className="text-xs text-down">{problem}</span>}
        <button
          type="button"
          onClick={() => {
            setRules(toDraft(DEFAULT_SCREEN))
            setPicked([])
            setSort(DEFAULT_SCREEN.sort ?? '')
            setDescending(true)
            setColumns([])
            setLargeOnly(false)
            setProblem(null)
          }}
          className="text-xs text-muted hover:text-fg"
        >
          Reset
        </button>
      </div>
    </div>
  )
}
