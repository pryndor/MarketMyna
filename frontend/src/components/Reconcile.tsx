import { useState } from 'react'
import {
  applyReconcileFixes,
  reconcilePortfolio,
  type PortfolioSummary,
  type ReconcileBreak,
  type ReconcileFix,
  type ReconcileReport,
} from '../api/portfolio'
import { cx } from '../lib/cx'
import { toBase64 } from '../lib/files'
import { errorMessage, num } from '../lib/format'
import { toast } from '../lib/toast'
import { Alert, Button, Card, CardBody, CardHeader, Field, Input } from './ui'

const MAX_BYTES = 10 * 1024 * 1024

const KIND: Record<ReconcileBreak['kind'], string> = {
  split: 'Split / bonus',
  not_in_app: 'Only on statement',
  not_in_statement: 'Only in MarketMyna',
  short: 'Statement has more',
  excess: 'MarketMyna has more',
}

/** Whole shares without decimals; fractional shares and fund units keep them. */
const qty = (v: number | null | undefined) => num(v, v != null && Number.isInteger(v) ? 0 : 4)

const FIX_LABEL: Record<ReconcileFix['type'], string> = { buy: 'Add buy', sell: 'Add sell', split: 'Add split / bonus' }

type Choice = { on: boolean; price: string }

/** Tie the portfolio out against a broker holdings export or a CAS statement:
 * every mismatch with its likely cause and a proposed entry, posted only when ticked. */
export default function Reconcile({
  portfolio,
  onCancel,
  onApplied,
}: {
  portfolio: string
  onCancel: () => void
  onApplied: (s: PortfolioSummary) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [password, setPassword] = useState('')
  const [checking, setChecking] = useState(false)
  const [applying, setApplying] = useState(false)
  const [report, setReport] = useState<ReconcileReport | null>(null)
  const [choices, setChoices] = useState<Record<string, Choice>>({})

  const isPdf = !!file && file.name.toLowerCase().endsWith('.pdf')
  const key = (b: ReconcileBreak, i: number) => `${b.symbol}:${i}`

  async function check() {
    if (!file) return
    if (file.size > MAX_BYTES) {
      toast.error('That file is over 10 MB')
      return
    }
    setChecking(true)
    try {
      const out = await reconcilePortfolio(portfolio, file.name, await toBase64(file), password)
      setReport(out)
      const next: Record<string, Choice> = {}
      for (const b of out.breaks) {
        b.fixes.forEach((f, i) => {
          // Splits and statement-priced buys are safe to pre-tick; anything needing a price is not.
          const price = f.type === 'split' ? '0' : f.price > 0 ? String(Math.round(f.price * 100) / 100) : ''
          next[key(b, i)] = { on: !f.needs_price, price }
        })
      }
      setChoices(next)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setChecking(false)
    }
  }

  async function apply() {
    if (!report) return
    const fixes = report.breaks.flatMap((b) =>
      b.fixes
        .map((f, i) => ({ b, f, c: choices[key(b, i)] }))
        .filter(({ c }) => c?.on)
        .map(({ b, f, c }) => ({
          symbol: b.symbol,
          market: b.market,
          type: f.type,
          quantity: f.quantity,
          price: f.type === 'split' ? 0 : Number(c.price),
          date: f.date,
          notes: f.notes,
        })),
    )
    if (!fixes.length) return
    if (fixes.some((f) => f.type !== 'split' && !(f.price > 0))) {
      toast.error('Enter a price for every ticked buy or sell')
      return
    }
    setApplying(true)
    try {
      const res = await applyReconcileFixes(portfolio, fixes)
      if (res.errors.length) toast.error(res.errors.join('; '))
      if (res.applied) toast.success(`Added ${res.applied} entr${res.applied === 1 ? 'y' : 'ies'}`)
      onApplied(res.portfolio)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setApplying(false)
    }
  }

  const ticked = Object.values(choices).filter((c) => c.on).length

  return (
    <Card className="mb-6" id="section-reconcile" section="Reconcile">
      <CardHeader
        title="Reconcile with a statement"
        icon="check"
        description="Compare this portfolio with the holdings export from your broker's website or app (CSV or Excel), or, for mutual funds, your Consolidated Account Statement (CAS) PDF. The file is read in memory and never stored."
      />
      <CardBody className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,14rem)_auto] sm:items-end">
          <Field label="Statement file">
            <Input type="file" accept=".csv,.xlsx,.xls,.pdf" onChange={(e) => (setFile(e.target.files?.[0] ?? null), setReport(null))} />
          </Field>
          {isPdf && (
            <Field label="CAS password" hint="Usually your PAN in capitals">
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
            </Field>
          )}
          <div className="flex gap-2">
            <Button icon="search" loading={checking} disabled={!file} onClick={check}>
              Check
            </Button>
            <Button variant="ghost" onClick={onCancel}>
              Close
            </Button>
          </div>
        </div>

        {report && (
          <>
            <div className="flex flex-wrap gap-2 text-sm">
              <span className="rounded-md bg-up-soft px-2 py-1 text-up">{report.matches.length} match</span>
              <span className={cx('rounded-md px-2 py-1', report.breaks.length ? 'bg-down-soft text-down' : 'bg-raised text-muted')}>
                {report.breaks.length} mismatch{report.breaks.length === 1 ? '' : 'es'}
              </span>
              {report.cost_differences.length > 0 && (
                <span className="rounded-md bg-raised px-2 py-1 text-muted">{report.cost_differences.length} cost difference{report.cost_differences.length === 1 ? '' : 's'}</span>
              )}
              <span className="px-1 py-1 text-xs text-faint">
                {report.rows_read} lines read from the {report.kind === 'cas' ? 'CAS (mutual funds only)' : 'broker statement (Indian stocks and ETFs only)'}
              </span>
            </div>

            {report.ledger.length > 0 && (
              <Alert tone="warn" title="Your holdings and transaction history disagree">
                {report.ledger.map((l) => (
                  <div key={`${l.symbol}`}>
                    {l.symbol ? `${l.symbol}: ` : ''}
                    {l.issue}
                    {l.stored != null && ` (holding ${qty(l.stored)}, history ${qty(l.from_history)})`}
                  </div>
                ))}
              </Alert>
            )}

            {report.unresolved.length > 0 && (
              <Alert tone="warn" title={`${report.unresolved.length} statement line${report.unresolved.length === 1 ? '' : 's'} not recognised`}>
                {report.unresolved.map((u) => `${u.name || u.symbol}${u.isin ? ` (${u.isin})` : ''}: ${qty(u.quantity)}`).join(' · ')}
                . Add these by hand if you hold them.
              </Alert>
            )}

            {report.breaks.length === 0 ? (
              <p className="rounded-lg bg-up-soft px-4 py-3 text-sm text-up">Everything on the statement agrees with this portfolio.</p>
            ) : (
              <div className="space-y-3">
                {report.breaks.map((b) => (
                  <div key={b.symbol} className="rounded-lg border border-line p-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <span className="font-mono text-sm font-semibold">{b.symbol}</span>
                        {b.name && <span className="ms-2 text-xs text-muted">{b.name}</span>}
                        <span className="ms-2 rounded bg-raised px-1.5 py-0.5 text-[11px] text-muted">{KIND[b.kind]}</span>
                      </div>
                      <div className="tabular text-xs text-muted">
                        Statement {qty(b.statement_qty)} · MarketMyna {qty(b.app_qty)}
                      </div>
                    </div>
                    <p className="mt-1 text-xs text-muted">{b.cause}</p>
                    <div className="mt-2 space-y-1.5">
                      {b.fixes.map((f, i) => {
                        const c = choices[key(b, i)] ?? { on: false, price: '' }
                        return (
                          <label key={i} className="flex flex-wrap items-center gap-2 text-sm">
                            <input
                              type="checkbox"
                              className="accent-accent"
                              checked={c.on}
                              onChange={(e) => setChoices((p) => ({ ...p, [key(b, i)]: { ...c, on: e.target.checked } }))}
                            />
                            <span>
                              {FIX_LABEL[f.type]}: {f.type === 'split' ? `${num(f.quantity, 2)} shares per old share` : qty(f.quantity)} on {f.date}
                            </span>
                            {f.type !== 'split' && (
                              <span className="inline-flex items-center gap-1">
                                <span className="text-xs text-muted">at</span>
                                <Input
                                  type="number"
                                  min="0"
                                  step="any"
                                  className="h-8 w-28"
                                  value={c.price}
                                  onChange={(e) => setChoices((p) => ({ ...p, [key(b, i)]: { ...c, price: e.target.value } }))}
                                />
                                {f.needs_price && <span className="text-xs text-warn">check the price</span>}
                              </span>
                            )}
                          </label>
                        )
                      })}
                    </div>
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-3">
                  <Button icon="check" loading={applying} disabled={!ticked} onClick={apply}>
                    Add {ticked} ticked entr{ticked === 1 ? 'y' : 'ies'}
                  </Button>
                  <span className="text-xs text-faint">Nothing changes until you add them. Each becomes a normal transaction you can delete later.</span>
                </div>
              </div>
            )}

            {report.cost_differences.length > 0 && (
              <details className="text-xs text-muted">
                <summary className="cursor-pointer">Average cost differs on {report.cost_differences.length} matched holding{report.cost_differences.length === 1 ? '' : 's'} (information only)</summary>
                <ul className="mt-2 space-y-1">
                  {report.cost_differences.map((c) => (
                    <li key={c.symbol} className="tabular">
                      <span className="font-mono">{c.symbol}</span>: statement {num(c.statement_avg, 2)}, MarketMyna {num(c.app_avg, 2)}
                    </li>
                  ))}
                </ul>
                <p className="mt-1">{report.cost_differences[0].cause}</p>
              </details>
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}
