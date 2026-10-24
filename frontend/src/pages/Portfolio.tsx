import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  addTransaction,
  createPortfolio,
  deletePortfolio,
  deleteTransaction,
  getFundNav,
  getPortfolio,
  listPortfolios,
  renamePortfolio,
  type Holding,
  type PortfolioKind,
  type PortfolioSummary,
  type TransactionType,
} from '../api/portfolio'
import { toast } from '../lib/toast'
import SymbolSearch from '../components/SymbolSearch'
import PortfolioAnalytics from '../components/PortfolioAnalytics'
import PortfolioReview from '../components/PortfolioReview'
import ImportCAS from '../components/ImportCAS'
import Reconcile from '../components/Reconcile'
import FundInsights from '../components/FundInsights'
import FundsAiReview from '../components/FundsAiReview'
import FundPortfolio from '../components/FundPortfolio'
import ExportMenu from '../components/ExportMenu'
import SectionIndex from '../components/SectionIndex'
import type { ExportTable } from '../lib/exporter'
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Field,
  Icon,
  Input,
  PageHeader,
  Segmented,
  Select,
  Skeleton,
  Stat,
} from '../components/ui'
import { cx } from '../lib/cx'
import { errorMessage, money, num, pct, signed, trendClass } from '../lib/format'
import { CURRENCIES, MARKETS, type Option } from '../lib/options'

// Markets for a transaction: listed markets plus Indian mutual funds (by AMFI code).
const TX_MARKETS: Option[] = [...MARKETS, { value: 'mf', label: 'Mutual fund' }]

const TX_TYPES: Option<TransactionType>[] = [
  { value: 'buy', label: 'Buy' },
  { value: 'sell', label: 'Sell' },
  { value: 'dividend', label: 'Dividend' },
  { value: 'split', label: 'Split / bonus' },
]

const ALLOCATION_COLORS = ['#6d8cff', '#34d399', '#fbbf24', '#f472b6', '#22d3ee', '#a78bfa', '#fb923c', '#94a3b8']

type SortKey = 'symbol' | 'market_value' | 'unrealized_gain' | 'unrealized_gain_percent' | 'weight'

export default function PortfolioPage() {
  const [names, setNames] = useState<string[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [loaded, setSummary] = useState<PortfolioSummary | null>(null)
  // Only ever show the selected portfolio's data: a slower response for the
  // tab you just left must not paint another portfolio's holdings here.
  const summary = loaded && loaded.name === selected ? loaded : null
  // Changes with the holdings, so the cards below refetch.
  const holdingsVersion = summary ? Object.values(summary.holdings).map((h) => `${h.symbol}:${h.quantity}`).join(',') : ''
  const hasFunds = !!summary && Object.values(summary.holdings).some((h) => h.market?.toLowerCase() === 'mf')
  const loadSeq = useRef(0)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [reconciling, setReconciling] = useState(false)
  // Bumped by "Add mutual fund manually": re-opens the transaction form in fund mode.
  const [fundEntry, setFundEntry] = useState(0)
  const contentRef = useRef<HTMLDivElement>(null)
  // "Add to portfolio" on a stock page links here with ?add=SYMBOL&market=..&price=..
  const [params, setParams] = useSearchParams()
  const prefill = useMemo(() => {
    const symbol = params.get('add')
    return symbol ? { symbol, market: params.get('market') ?? 'us', price: params.get('price') ?? '' } : null
  }, [params])
  const clearPrefill = useCallback(() => setParams({}, { replace: true }), [setParams])

  const refreshNames = useCallback(async (select?: string) => {
    try {
      const list = await listPortfolios()
      setNames(list)
      setSelected((cur) => select ?? cur ?? list[0] ?? null)
    } catch (err) {
      setNames([])
      toast.error(errorMessage(err))
    }
  }, [])

  const load = useCallback(async (name: string) => {
    const seq = ++loadSeq.current
    setLoading(true)
    try {
      const data = await getPortfolio(name)
      if (seq === loadSeq.current) setSummary(data)
    } catch (err) {
      if (seq !== loadSeq.current) return
      setSummary(null)
      toast.error(errorMessage(err))
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshNames()
  }, [refreshNames])

  useEffect(() => {
    if (selected) load(selected)
  }, [selected, load])

  return (
    <div>
      <PageHeader
        title="Portfolio"
        description="Holdings, live valuation and transaction entry."
        actions={
          <>
            {selected && summary && (
              <ExportMenu title={`Portfolio ${selected}`} subtitle={`Currency ${summary.currency}`} tables={() => exportPortfolio(summary)} />
            )}
            {selected && (
              <Button variant="secondary" icon="refresh" loading={loading} onClick={() => load(selected)}>
                Refresh prices
              </Button>
            )}

            <Button icon="plus" onClick={() => setCreating(true)}>
              New portfolio
            </Button>
          </>
        }
      />


      {creating && (
        <CreatePortfolioForm
          existing={names ?? []}
          onCancel={() => setCreating(false)}
          onCreated={(name) => {
            setCreating(false)
            refreshNames(name)
          }}
        />
      )}

      {names == null ? (
        <Skeleton className="h-40 w-full" />
      ) : names.length === 0 ? (
        !creating && (
          <Card>
            <EmptyState
              icon="portfolio"
              title="No portfolios yet"
              description={
                prefill
                  ? `Create a portfolio first, then ${prefill.symbol} is ready to record.`
                  : 'Create your own portfolio, then record buys and sells to track value and unrealized P/L.'
              }
              action={<Button icon="plus" onClick={() => setCreating(true)}>New portfolio</Button>}
            />
          </Card>
        )
      ) : (
        <>
          <div className="mb-5 flex gap-1 overflow-x-auto border-b border-line">
            {names.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setSelected(n)}
                className={cx(
                  '-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium',
                  n === selected ? 'border-accent text-fg' : 'border-transparent text-muted hover:text-fg',
                )}
              >
                {n}
              </button>
            ))}
          </div>

          {selected && (
            <ManageBar
              key={selected}
              name={selected}
              existing={names}
              onRenamed={(next, updated) => {
                setSummary(updated)
                refreshNames(next)
              }}
              onImport={() => setImporting((v) => !v)}
              onReconcile={() => setReconciling((v) => !v)}
              onAddFund={() => {
                setFundEntry((n) => n + 1)
                setTimeout(() => document.getElementById('tx-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50)
              }}
              onDeleted={() => {
                setSummary(null)
                setSelected(null)
                refreshNames()
              }}
            />
          )}

          {importing && selected && summary && (
            <ImportCAS
              key={selected}
              portfolio={selected}
              currency={summary.currency}
              onCancel={() => setImporting(false)}
              onImported={(updated) => {
                setSummary(updated)
                setImporting(false)
              }}
            />
          )}

          {reconciling && selected && (
            <Reconcile
              key={selected}
              portfolio={selected}
              onCancel={() => setReconciling(false)}
              onApplied={(updated) => setSummary(updated)}
            />
          )}

          {summary && selected ? (
            // Wide screens: content left, sidebar (jump index + entry form) right.
            // Narrower: one column in the old order - summary, holdings, form, the rest.
            <div className="flex flex-col gap-6 xl:grid xl:grid-cols-[minmax(0,1fr)_340px]">
              <div ref={contentRef} className="contents xl:block xl:min-w-0 xl:space-y-6">
                <div className="min-w-0 space-y-6">
                  <SummaryStats summary={summary} />
                  <HoldingsCard summary={summary} />
                  {Object.keys(summary.holdings).length > 0 && (
                    <PortfolioReview
                      portfolio={selected}
                      version={`${holdingsVersion}|${summary.cash_balance}`}
                    />
                  )}
                </div>
                <div className="order-2 min-w-0 space-y-6 xl:order-none">
                  {Object.keys(summary.holdings).length > 0 && (
                    <PortfolioAnalytics
                      portfolio={selected}
                      currency={summary.currency}
                      version={holdingsVersion}
                    />
                  )}
                  {hasFunds && (
                    <FundPortfolio
                      portfolio={selected}
                      version={holdingsVersion}
                    />
                  )}
                  {hasFunds && (
                    <FundInsights
                      portfolio={selected}
                      version={holdingsVersion}
                    />
                  )}
                  {hasFunds && (
                    <FundsAiReview
                      portfolio={selected}
                      version={holdingsVersion}
                    />
                  )}
                  <TransactionsCard summary={summary} onChanged={setSummary} />
                </div>
              </div>
              <aside className="order-1 min-w-0 xl:order-none">
                {/* Index + form share one sticky column capped at the window
                    height; the index gives up space (its list scrolls) so the
                    form always fits. Too short for both: neither sticks. */}
                <div className="z-10 flex flex-col gap-6 xl:sticky xl:top-8 xl:max-h-[calc(100vh-4rem)] [@media(max-height:800px)]:static [@media(max-height:800px)]:max-h-none">
                {Object.keys(summary.holdings).length > 0 && (
                  <div className="hidden min-h-36 flex-col xl:flex">
                    <SectionIndex key={selected} root={contentRef} fill />
                  </div>
                )}
                <TransactionForm
                  key={prefill ? `${selected}:${prefill.symbol}` : `${selected}:${fundEntry}`}
                  portfolio={selected}
                  prefill={prefill}
                  fundMode={fundEntry > 0}
                  onSaved={(updated) => {
                    setSummary(updated)
                    if (prefill) clearPrefill()
                  }}
                />
                </div>
              </aside>
            </div>
          ) : (
            <Skeleton className="h-64 w-full" />
          )}
        </>
      )}
    </div>
  )
}

function CreatePortfolioForm({
  existing,
  onCancel,
  onCreated,
}: {
  existing: string[]
  onCancel: () => void
  onCreated: (name: string) => void
}) {
  const [name, setName] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [kind, setKind] = useState<PortfolioKind>('stocks')
  const [saving, setSaving] = useState(false)
  const clean = name.trim()
  const duplicate = existing.includes(clean)

  async function submit() {
    if (!clean || duplicate) return
    setSaving(true)
    try {
      await createPortfolio(clean, currency, kind)
      toast.success(`Portfolio “${clean}” created`)
      onCreated(clean)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="mb-6">
      <form
        className="grid items-end gap-4 p-5 sm:grid-cols-[minmax(0,1fr)_160px_140px_auto]"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <Field label="Portfolio name">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Ravi - Long term"
            maxLength={60}
            autoFocus
            aria-describedby="portfolio-name-hint"
          />
        </Field>
        {/* Under the name on phones; under the whole row from sm up (order-last),
            so the input, select and buttons share one bottom line. */}
        <p id="portfolio-name-hint" className="-mt-2 text-xs text-faint sm:order-last sm:col-span-4">
          {duplicate ? (
            <span className="text-down">Name already exists</span>
          ) : (
            'Put your name in it so others know it is yours. Free includes one stocks and one mutual fund portfolio.'
          )}
        </p>
        <Field label="Holds">
          <Select
            options={[
              { value: 'stocks', label: 'Stocks' },
              { value: 'funds', label: 'Mutual funds' },
            ]}
            value={kind}
            onChange={(e) => setKind(e.target.value as PortfolioKind)}
          />
        </Field>
        <Field label="Base currency">
          <Select options={CURRENCIES.map((c) => ({ value: c, label: c }))} value={currency} onChange={(e) => setCurrency(e.target.value)} />
        </Field>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" loading={saving} disabled={!clean || duplicate}>
            Create
          </Button>
        </div>
      </form>
    </Card>
  )
}

function SummaryStats({ summary }: { summary: PortfolioSummary }) {
  const c = summary.currency
  return (
    <Card id="section-summary" section="Summary">
      <div className="grid grid-cols-2 gap-6 p-5 md:grid-cols-5">
        <Stat label="Total value" value={money(summary.total_value, c)} />
        <Stat label="Market value" value={money(summary.total_market_value, c)} />
        <Stat label="Cost basis" value={money(summary.total_cost_basis, c)} />
        <Stat
          label="Unrealized P/L"
          value={<span className={trendClass(summary.total_unrealized_gain)}>{signed(summary.total_unrealized_gain)}</span>}
          sub={pct(summary.total_unrealized_gain_percent)}
          subClassName={trendClass(summary.total_unrealized_gain)}
        />
        <Stat label="Cash" value={money(summary.cash_balance, c)} />
      </div>
    </Card>
  )
}

/** Where a holding opens in Analyze: funds (AMFI codes, India) get the fund view. */
function analyzeLink(h: Holding): string {
  const symbol = encodeURIComponent(h.symbol)
  return h.market?.toLowerCase() === 'mf'
    ? `/analyze?view=funds&symbol=${symbol}&market=india`
    : `/analyze?symbol=${symbol}&market=${encodeURIComponent((h.market || 'us').toLowerCase())}`
}

function HoldingsCard({ summary }: { summary: PortfolioSummary }) {
  const navigate = useNavigate()
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'market_value', dir: -1 })

  const rows = useMemo(() => {
    const total = summary.total_market_value || 0
    const list = Object.values(summary.holdings).map((h) => ({
      ...h,
      weight: total ? ((h.market_value ?? 0) / total) * 100 : 0,
    }))
    return list.sort((a, b) => {
      const av = a[sort.key] ?? 0
      const bv = b[sort.key] ?? 0
      return (typeof av === 'string' ? av.localeCompare(String(bv)) : Number(av) - Number(bv)) * sort.dir
    })
  }, [summary, sort])

  function header(key: SortKey, label: string, align: 'left' | 'right' = 'right') {
    const activeSort = sort.key === key
    return (
      <th className={cx('px-3 py-2.5 font-medium', align === 'right' ? 'text-end' : 'text-start')}>
        <button
          type="button"
          onClick={() => setSort({ key, dir: activeSort ? (sort.dir === 1 ? -1 : 1) : -1 })}
          className={cx('inline-flex items-center gap-1 hover:text-fg', activeSort && 'text-fg')}
        >
          {label}
          {activeSort && <span className="text-[12px]">{sort.dir === 1 ? '▲' : '▼'}</span>}
        </button>
      </th>
    )
  }

  return (
    <Card id="section-holdings" section="Holdings" className="min-w-0">
      <CardHeader title="Holdings" description={`${rows.length} position${rows.length === 1 ? '' : 's'}`} />
      {rows.length === 0 ? (
        <EmptyState icon="portfolio" title="No holdings" description="Record a Buy transaction to open a position." />
      ) : (
        <>
          <div className="flex h-2 overflow-hidden rounded-none">
            {rows.map((h, i) => (
              <div
                key={h.symbol}
                title={`${h.name ?? h.symbol} ${num(h.weight, 1)}%`}
                style={{ width: `${h.weight}%`, background: ALLOCATION_COLORS[i % ALLOCATION_COLORS.length] }}
              />
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="tabular w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  {header('symbol', 'Symbol', 'left')}
                  <th className="px-3 py-2.5 text-end font-medium">Qty</th>
                  <th className="px-3 py-2.5 text-end font-medium">Avg cost</th>
                  <th className="px-3 py-2.5 text-end font-medium">Price</th>
                  {header('market_value', 'Value')}
                  {header('weight', 'Weight')}
                  {header('unrealized_gain', 'P/L')}
                  {header('unrealized_gain_percent', 'P/L %')}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((h: Holding & { weight: number }, i) => (
                  <tr
                    key={h.symbol}
                    className="cursor-pointer hover:bg-raised/40"
                    title="Open in Analyze"
                    onClick={(e) => {
                      if (!(e.target as HTMLElement).closest('a')) navigate(analyzeLink(h))
                    }}
                  >
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-sm" style={{ background: ALLOCATION_COLORS[i % ALLOCATION_COLORS.length] }} />
                        {h.market?.toLowerCase() === 'mf' ? (
                          <Link to={analyzeLink(h)} className="group min-w-0" title={`${h.name ?? h.symbol} · AMFI ${h.symbol} · open the fund analysis`}>
                            <span className="block max-w-56 truncate font-medium group-hover:text-accent-fg">{h.name ?? h.symbol}</span>
                            <span className="block text-xs text-faint">{h.category?.replace(/ Scheme - /, ' · ') || 'Mutual fund'}</span>
                          </Link>
                        ) : (
                          <Link
                            to={analyzeLink(h)}
                            className="font-mono font-medium hover:text-accent-fg"
                            title="Open in Analyze"
                          >
                            {h.symbol}
                          </Link>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-end">{num(h.quantity, h.quantity % 1 ? 4 : 0)}</td>
                    <td className="px-3 py-2.5 text-end text-muted">{num(h.avg_cost)}</td>
                    <td className="px-3 py-2.5 text-end">{num(h.current_price)}</td>
                    <td className="px-3 py-2.5 text-end">{num(h.market_value)}</td>
                    <td className="px-3 py-2.5 text-end text-muted">{num(h.weight, 1)}%</td>
                    <td className={cx('px-3 py-2.5 text-end', trendClass(h.unrealized_gain))}>{signed(h.unrealized_gain)}</td>
                    <td className={cx('px-3 py-2.5 text-end', trendClass(h.unrealized_gain_percent))}>{pct(h.unrealized_gain_percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  )
}

/** Rename or delete the selected portfolio. Delete asks twice. */
function ManageBar({
  name,
  existing,
  onRenamed,
  onDeleted,
  onImport,
  onReconcile,
  onAddFund,
}: {
  name: string
  existing: string[]
  onRenamed: (next: string, updated: PortfolioSummary) => void
  onDeleted: () => void
  onImport: () => void
  onReconcile: () => void
  onAddFund: () => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [value, setValue] = useState(name)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const clean = value.trim()
  const duplicate = clean !== name && existing.includes(clean)

  async function rename() {
    if (!clean || duplicate || clean === name) return setRenaming(false)
    setBusy(true)
    try {
      const updated = await renamePortfolio(name, clean)
      toast.success(`Renamed to “${clean}”`)
      setRenaming(false)
      onRenamed(clean, updated)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    try {
      await deletePortfolio(name)
      toast.success(`Portfolio “${name}” deleted`)
      onDeleted()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mb-5 flex flex-wrap items-center gap-2">
      {renaming ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            rename()
          }}
        >
          <Input value={value} onChange={(e) => setValue(e.target.value)} maxLength={60} className="h-8 w-64" autoFocus />
          <Button type="submit" size="sm" loading={busy} disabled={!clean || duplicate}>
            Save
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => (setRenaming(false), setValue(name))}>
            Cancel
          </Button>
          {duplicate && <span className="text-xs text-down">Name already exists</span>}
        </form>
      ) : confirming ? (
        <>
          <span className="text-sm text-down">Delete “{name}” with all its holdings and transactions? This can't be undone.</span>
          <Button size="sm" variant="danger" icon="trash" loading={busy} onClick={remove}>
            Yes, delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Keep it
          </Button>
        </>
      ) : (
        <>
          <Button size="sm" variant="ghost" icon="pencil" onClick={() => setRenaming(true)}>
            Rename
          </Button>
          <Button size="sm" variant="ghost" icon="trash" onClick={() => setConfirming(true)}>
            Delete portfolio
          </Button>
          <Button size="sm" variant="ghost" icon="plus" onClick={onAddFund}>
            Add mutual fund manually
          </Button>
          <Button size="sm" variant="ghost" icon="plus" onClick={onImport}>
            Import mutual funds (CAS)
          </Button>
          <Button size="sm" variant="ghost" icon="check" onClick={onReconcile}>
            Reconcile with statement
          </Button>
        </>
      )}
    </div>
  )
}

/** Full history, newest first, with a delete for mistakes. Holdings are
 * rebuilt on the server from what remains. */
function TransactionsCard({ summary, onChanged }: { summary: PortfolioSummary; onChanged: (s: PortfolioSummary) => void }) {
  const [pending, setPending] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const rows = [...(summary.transactions ?? [])].reverse()

  async function remove(index: number) {
    setBusy(true)
    try {
      onChanged(await deleteTransaction(summary.name, index))
      toast.success('Transaction removed - holdings recalculated')
      setPending(null)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card id="section-transactions" section="Transactions">
      <CardHeader title="Transactions" description="Entered something wrong? Delete it and the holdings are recalculated." />
      {rows.length === 0 ? (
        <EmptyState icon="portfolio" title="No transactions yet" description="Record a Buy to start." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-y border-line text-xs text-muted">
                <th className="px-5 py-2 text-start font-medium">Date</th>
                <th className="px-3 py-2 text-start font-medium">Type</th>
                <th className="px-3 py-2 text-start font-medium">Symbol</th>
                <th className="px-3 py-2 text-end font-medium">Qty</th>
                <th className="px-3 py-2 text-end font-medium">Price</th>
                <th className="hidden px-3 py-2 text-end font-medium sm:table-cell">Total</th>
                <th className="hidden px-3 py-2 text-start font-medium md:table-cell">Notes</th>
                <th className="px-5 py-2" aria-label="Actions" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((t) => (
                <tr key={t.index}>
                  <td className="tabular px-5 py-2.5 text-muted">{t.date ? t.date.slice(0, 10) : '—'}</td>
                  <td className={cx('px-3 py-2.5 font-medium uppercase', t.transaction_type === 'buy' ? 'text-up' : t.transaction_type === 'sell' ? 'text-down' : 'text-muted')}>
                    {t.transaction_type}
                  </td>
                  <td className="px-3 py-2.5 font-mono">{t.symbol}</td>
                  <td className="tabular px-3 py-2.5 text-end">{num(t.quantity, 0)}</td>
                  <td className="tabular px-3 py-2.5 text-end">{num(t.price)}</td>
                  <td className="tabular hidden px-3 py-2.5 text-end sm:table-cell">{num(t.total)}</td>
                  <td className="hidden max-w-48 truncate px-3 py-2.5 text-muted md:table-cell" title={t.notes}>
                    {t.notes || '—'}
                  </td>
                  <td className="px-5 py-2.5 text-end whitespace-nowrap">
                    {pending === t.index ? (
                      <span className="inline-flex items-center gap-1">
                        <Button size="sm" variant="danger" loading={busy} onClick={() => remove(t.index)}>
                          Delete
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setPending(null)}>
                          Cancel
                        </Button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setPending(t.index)}
                        className="rounded-md p-1.5 text-faint hover:bg-raised hover:text-down"
                        aria-label={`Delete ${t.transaction_type} ${t.symbol}`}
                        title="Delete"
                      >
                        <Icon name="trash" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function TransactionForm({
  portfolio,
  prefill,
  fundMode = false,
  onSaved,
}: {
  portfolio: string
  prefill?: { symbol: string; market: string; price: string } | null
  /** Opened from "Add mutual fund manually": start on market "Mutual fund". */
  fundMode?: boolean
  onSaved: (s: PortfolioSummary) => void
}) {
  const [type, setType] = useState<TransactionType>('buy')
  const [symbol, setSymbol] = useState(prefill?.symbol ?? '')
  const [market, setMarket] = useState(prefill?.market ?? (fundMode ? 'mf' : 'us'))
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState(prefill?.price ?? '')
  const [fees, setFees] = useState('')
  const [date, setDate] = useState(today)
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  // Funds: amount invested -> units, and the official NAV for the trade date.
  const [amount, setAmount] = useState('')
  const [navInfo, setNavInfo] = useState<{ date: string } | 'loading' | 'missing' | null>(null)

  const qty = Number(quantity)
  const px = Number(price)
  const fee = Number(fees || 0)
  const isSplit = type === 'split'
  const valid = symbol.trim() !== '' && qty > 0 && px >= 0 && (price !== '' || isSplit) && fee >= 0
  const total = !valid || type === 'split' ? null : type === 'buy' ? qty * px + fee : qty * px - fee

  const isFund = market === 'mf'
  const priceLabel = type === 'dividend' ? 'Amount per share' : isFund ? 'NAV' : 'Price'
  const fundTrade = isFund && (type === 'buy' || type === 'sell')
  const fundCode = /^\d+$/.test(symbol.trim()) ? symbol.trim() : ''

  // Fill in the official NAV once a fund and date are picked.
  useEffect(() => {
    if (!fundTrade || !fundCode || !date) {
      setNavInfo(null)
      return
    }
    let stale = false
    setNavInfo('loading')
    getFundNav(fundCode, date)
      .then((r) => {
        if (stale) return
        setPrice(String(r.nav))
        setNavInfo({ date: r.nav_date })
      })
      .catch(() => !stale && setNavInfo('missing'))
    return () => {
      stale = true
    }
  }, [fundTrade, fundCode, date])

  // Amount invested -> units, the way the fund house allots them: 0.005%
  // stamp duty comes off a purchase, then amount / NAV to 3 decimals.
  useEffect(() => {
    const amt = Number(amount)
    const nav = Number(price)
    if (!fundTrade || amount === '' || !(amt > 0) || !(nav > 0)) return
    const net = type === 'buy' ? amt * (1 - 0.00005) : amt
    setQuantity(String(Math.floor((net / nav) * 1000) / 1000))
  }, [amount, price, type, fundTrade])

  async function submit() {
    if (!valid) return
    setSaving(true)
    try {
      const updated = await addTransaction(portfolio, {
        symbol: symbol.trim().toUpperCase(),
        transaction_type: type,
        quantity: qty,
        price: px,
        fees: fee,
        notes: notes.trim(),
        market: market.toUpperCase(),
        date: date ? new Date(`${date}T12:00:00`).toISOString() : undefined,
      })
      onSaved(updated)
      toast.success(`${type.toUpperCase()} ${qty} ${symbol.trim().toUpperCase()} recorded`)
      setSymbol('')
      setQuantity('')
      setPrice('')
      setFees('')
      setNotes('')
      setAmount('')
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card id="tx-form" className="h-fit">
      <CardHeader
        title={market === 'mf' ? 'Add a mutual fund' : 'Record transaction'}
        description={market === 'mf' ? `Into ${portfolio} · units and NAV are on your fund statement or app` : `Into ${portfolio}`}
        icon="plus"
      />
      <CardBody>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <Segmented options={TX_TYPES} value={type} onChange={(v) => setType(v as TransactionType)} size="sm" />
          <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-3">
            <Field label="Symbol">
              <SymbolSearch
                value={symbol}
                onChange={setSymbol}
                onSelect={(row) => {
                  setSymbol(row.symbol)
                  // A mutual fund is kept by its AMFI scheme code under market "mf".
                  setMarket(row.type === 'mf' ? 'mf' : row.market)
                }}
                type={market === 'mf' ? 'mf' : 'all'}
                autoFocus={fundMode}
                placeholder={market === 'mf' ? 'Search a fund, e.g. Parag Parikh Flexi Cap Direct' : 'Search a stock, ETF or mutual fund'}
              />
            </Field>
            <Field label="Market">
              <Select options={TX_MARKETS} value={market} onChange={(e) => setMarket(e.target.value)} />
            </Field>
          </div>
          {fundTrade && (
            <Field
              label={type === 'buy' ? 'Amount invested (₹)' : 'Amount received (₹)'}
              hint="Optional. Units are worked out from this and the NAV. Or type the units yourself below."
            >
              <Input type="number" min="0" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="e.g. 5000" />
            </Field>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Field
              label={isSplit ? 'Shares now per 1 old share' : isFund ? 'Units' : 'Quantity'}
              hint={
                isSplit
                  ? '5 for a 1:5 split, 2 for a 1:1 bonus'
                  : fundTrade
                    ? (amount ? 'From the amount and NAV' : 'On your statement or fund app')
                    : undefined
              }
            >
              <Input
                type="number"
                min="0"
                step="any"
                value={quantity}
                onChange={(e) => {
                  setQuantity(e.target.value)
                  setAmount('')
                }}
                placeholder="0"
              />
            </Field>
            {!isSplit && (
              <Field
                label={priceLabel}
                hint={
                  !fundTrade
                    ? undefined
                    : navInfo === 'loading'
                      ? 'Looking up NAV…'
                      : navInfo === 'missing'
                        ? 'NAV not found, type it in'
                        : navInfo
                          ? `Official NAV of ${navInfo.date}`
                          : 'Pick the fund and date first'
                }
              >
                <Input type="number" min="0" step="any" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="0.00" />
              </Field>
            )}
            {!isSplit && (
              <Field label="Fees">
                <Input type="number" min="0" step="any" value={fees} onChange={(e) => setFees(e.target.value)} placeholder="0.00" />
              </Field>
            )}
            <Field label="Trade date">
              <Input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} />
            </Field>
          </div>
          <Field label="Notes" hint="Optional">
            <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Reason, broker, lot…" />
          </Field>

          <div className="flex items-center justify-between rounded-lg bg-canvas px-3 py-2.5 text-sm">
            <span className="text-muted">{type === 'buy' ? 'Total cost' : type === 'split' ? 'Cash impact' : 'Net proceeds'}</span>
            <span className="tabular font-semibold">{num(total)}</span>
          </div>

          <Button type="submit" icon="check" className="w-full" loading={saving} disabled={!valid}>
            Record {type}
          </Button>
        </form>
      </CardBody>
    </Card>
  )
}


function exportPortfolio(summary: PortfolioSummary): ExportTable[] {
  const total = summary.total_market_value || 0
  const holdings = Object.values(summary.holdings).map((h) => ({
    ...h,
    display: h.market?.toLowerCase() === 'mf' ? h.name ?? h.symbol : h.symbol,
    weight: total ? ((h.market_value ?? 0) / total) * 100 : null,
  }))
  return [
    {
      title: 'Summary',
      columns: [{ key: 'label', label: 'Item' }, { key: 'value', label: 'Value', kind: 'number' }],
      rows: [
        { label: 'Market value', value: summary.total_market_value },
        { label: 'Cost basis', value: summary.total_cost_basis },
        { label: 'Unrealized P/L', value: summary.total_unrealized_gain },
        { label: 'Unrealized P/L %', value: summary.total_unrealized_gain_percent },
        { label: 'Cash', value: summary.cash_balance },
        { label: 'Total value', value: summary.total_value },
      ],
    },
    {
      title: 'Holdings',
      columns: [
        { key: 'display', label: 'Holding' }, { key: 'symbol', label: 'Symbol / AMFI code' }, { key: 'market', label: 'Market' },
        { key: 'category', label: 'Category' }, { key: 'quantity', label: 'Quantity', kind: 'number', digits: 4 },
        { key: 'avg_cost', label: 'Avg cost', kind: 'number' }, { key: 'current_price', label: 'Price', kind: 'number' },
        { key: 'market_value', label: 'Value', kind: 'number' }, { key: 'weight', label: 'Weight %', kind: 'pct' },
        { key: 'cost_basis', label: 'Cost', kind: 'number' }, { key: 'unrealized_gain', label: 'P/L', kind: 'number' },
        { key: 'unrealized_gain_percent', label: 'P/L %', kind: 'pct' },
      ],
      rows: holdings,
    },
    {
      title: 'Transactions',
      columns: [
        { key: 'date', label: 'Date', kind: 'date' }, { key: 'transaction_type', label: 'Type' }, { key: 'symbol', label: 'Symbol' },
        { key: 'market', label: 'Market' }, { key: 'quantity', label: 'Quantity', kind: 'number', digits: 4 },
        { key: 'price', label: 'Price', kind: 'number' }, { key: 'fees', label: 'Fees', kind: 'number' },
        { key: 'total', label: 'Total', kind: 'number' }, { key: 'notes', label: 'Notes' },
      ],
      rows: summary.transactions ?? [],
    },
  ]
}
