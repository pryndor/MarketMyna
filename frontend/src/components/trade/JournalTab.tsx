import { useCallback, useEffect, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { addTrade, deleteTrade, getJournal, updateTrade, type JournalData, type NewTrade, type Product, type Trade } from '../../api/trade'
import { cx } from '../../lib/cx'
import { errorMessage, num, price as fmtPrice } from '../../lib/format'
import { MARKETS, labelFor } from '../../lib/options'
import { toast } from '../../lib/toast'
import SymbolSearch from '../SymbolSearch'
import { Button, Card, CardBody, CardHeader, EmptyState, Field, Icon, Input, Segmented, Select, Skeleton } from '../ui'
import { CURRENCY } from './shared'
import StatTile from './StatTile'

export interface JournalDraft {
  symbol: string
  market: string
  side: 'long' | 'short'
  quantity: string
  entry_price: string
  stop: string
  target: string
  fees: string
  product: string
  setup: string
  notes: string
}

export function emptyDraft(symbol: string, market: string): JournalDraft {
  return {
    symbol,
    market,
    side: 'long',
    quantity: '',
    entry_price: '',
    stop: '',
    target: '',
    fees: '',
    product: market === 'india' ? 'delivery' : '',
    setup: '',
    notes: '',
  }
}

const SETUPS = ['breakout', 'pullback', 'reversal', 'gap', 'trend', 'range', 'news']

function toNumber(s: string): number | undefined {
  const v = parseFloat(s)
  return Number.isFinite(v) ? v : undefined
}

export default function JournalTab({
  draft,
  setDraft,
}: {
  draft: JournalDraft
  setDraft: (d: JournalDraft) => void
}) {
  const [market, setMarket] = useState('')
  const [marketPicked, setMarketPicked] = useState(false)
  const [data, setData] = useState<JournalData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [closing, setClosing] = useState<Record<number, string>>({})
  const [search, setSearch] = useState(draft.symbol)

  const load = useCallback(() => {
    getJournal(market || undefined)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((err) => setError(errorMessage(err)))
  }, [market])

  useEffect(load, [load])
  useEffect(() => setSearch(draft.symbol), [draft.symbol])

  // Stats mix currencies when markets are mixed; default to one market.
  useEffect(() => {
    if (data && !marketPicked && !market && data.markets.length > 1) setMarket(data.markets[0])
  }, [data, market, marketPicked])

  async function save() {
    const quantity = toNumber(draft.quantity)
    const entry = toNumber(draft.entry_price)
    if (!draft.symbol || !quantity || !entry) return
    setSaving(true)
    try {
      const body: Partial<NewTrade> = {
        symbol: draft.symbol,
        market: draft.market,
        side: draft.side,
        quantity,
        entry_price: entry,
        stop: toNumber(draft.stop) ?? null,
        target: toNumber(draft.target) ?? null,
        fees: toNumber(draft.fees) ?? null,
        product: draft.market === 'india' && draft.product ? (draft.product as Product) : null,
        setup: draft.setup,
        notes: draft.notes,
      }
      await addTrade(body)
      toast.success('Trade logged')
      setDraft(emptyDraft(draft.symbol, draft.market))
      load()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function close(t: Trade) {
    const exit = toNumber(closing[t.id] ?? '')
    if (!exit) return
    try {
      await updateTrade(t.id, { exit_price: exit })
      setClosing((c) => {
        const next = { ...c }
        delete next[t.id]
        return next
      })
      load()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function remove(t: Trade) {
    try {
      await deleteTrade(t.id)
      load()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const s = data?.stats
  const statCur = market ? CURRENCY[market] : undefined
  const set = (patch: Partial<JournalDraft>) => setDraft({ ...draft, ...patch })

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Log a trade" icon="plus" />
          <CardBody className="space-y-3">
            <div className="flex items-center gap-2">
              <Segmented
                options={[
                  { value: 'long', label: 'Long' },
                  { value: 'short', label: 'Short' },
                ]}
                value={draft.side}
                onChange={(v) => set({ side: v as 'long' | 'short' })}
                size="sm"
              />
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-2">
              <Field label="Symbol">
                <SymbolSearch
                  value={search}
                  onChange={(v) => {
                    setSearch(v)
                    set({ symbol: v.trim().toUpperCase() })
                  }}
                  onSelect={(row) => {
                    setSearch(row.symbol)
                    set({ symbol: row.symbol, market: row.market })
                  }}
                  market={draft.market}
                />
              </Field>
              <Field label="Market">
                <Select options={MARKETS} value={draft.market} onChange={(e) => set({ market: e.target.value })} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Quantity">
                <Input type="number" step="any" value={draft.quantity} onChange={(e) => set({ quantity: e.target.value })} />
              </Field>
              <Field label="Entry price">
                <Input type="number" step="any" value={draft.entry_price} onChange={(e) => set({ entry_price: e.target.value })} />
              </Field>
              <Field label="Stop">
                <Input type="number" step="any" value={draft.stop} onChange={(e) => set({ stop: e.target.value })} />
              </Field>
              <Field label="Target">
                <Input type="number" step="any" value={draft.target} onChange={(e) => set({ target: e.target.value })} />
              </Field>
              {draft.market === 'india' && (
                <Field label="Product">
                  <Select
                    options={[
                      { value: 'intraday', label: 'Intraday' },
                      { value: 'delivery', label: 'Delivery' },
                      { value: 'futures', label: 'Futures' },
                      { value: 'options', label: 'Options' },
                    ]}
                    value={draft.product || 'delivery'}
                    onChange={(e) => set({ product: e.target.value })}
                  />
                </Field>
              )}
              <Field label="Charges / fees" hint="Empty = estimated automatically">
                <Input type="number" step="any" value={draft.fees} placeholder="auto" onChange={(e) => set({ fees: e.target.value })} />
              </Field>
              <Field label="Setup">
                <Input list="setups" value={draft.setup} onChange={(e) => set({ setup: e.target.value })} placeholder="breakout" />
                <datalist id="setups">
                  {SETUPS.map((x) => (
                    <option key={x} value={x} />
                  ))}
                </datalist>
              </Field>
            </div>
            <Field label="Notes">
              <Input value={draft.notes} onChange={(e) => set({ notes: e.target.value })} placeholder="Why this trade, what you saw" />
            </Field>
            <Button onClick={save} loading={saving} disabled={!draft.symbol || !draft.quantity || !draft.entry_price}>
              Save open trade
            </Button>
            <p className="text-xs text-muted">Close it later from the list with the exit price. P&amp;L and R-multiple are computed.</p>
          </CardBody>
        </Card>

        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm font-medium">Performance</span>
            <Select
              className="w-44"
              options={[{ value: '', label: 'All markets' }, ...(data?.markets ?? []).map((m) => ({ value: m, label: labelFor(MARKETS, m) }))]}
              value={market}
              onChange={(e) => {
                setMarketPicked(true)
                setMarket(e.target.value)
              }}
            />
          </div>
          {error ? (
            <p className="text-sm text-down">{error}</p>
          ) : !s ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
                <StatTile label="Net P&L" value={fmtPrice(s.total_pnl, statCur)} tone={s.total_pnl >= 0 ? 'up' : 'down'} />
                <StatTile label="Win rate" value={s.win_rate != null ? `${s.win_rate}%` : '—'} sub={`${s.wins} W / ${s.losses} L`} />
                <StatTile label="Profit factor" value={num(s.profit_factor)} sub="gross win ÷ gross loss" />
                <StatTile label="Avg R" value={s.avg_r != null ? `${s.avg_r}R` : '—'} sub="profit ÷ risk taken" />
                <StatTile label="Expectancy" value={fmtPrice(s.expectancy, statCur)} sub="avg per trade" />
                <StatTile label="Avg win / loss" value={`${fmtPrice(s.avg_win, statCur)} / ${fmtPrice(s.avg_loss, statCur)}`} />
                <StatTile label="Best / worst" value={`${fmtPrice(s.best, statCur)} / ${fmtPrice(s.worst, statCur)}`} />
                <StatTile label="Losing streak" value={String(s.max_losing_streak)} sub={`${s.open} open`} />
              </div>
              {!market && (data?.markets.length ?? 0) > 1 && (
                <p className="text-xs text-warn">Totals mix currencies; pick a market for exact figures.</p>
              )}
              {s.equity.length > 1 && (
                <Card>
                  <CardHeader title="Equity curve" description="Cumulative net P&L of closed trades" />
                  <CardBody>
                    <div className="h-48">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={s.equity} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                          <CartesianGrid stroke="var(--color-line)" vertical={false} />
                          <XAxis
                            dataKey="date"
                            tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                            tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                            minTickGap={30}
                          />
                          <YAxis
                            orientation="right"
                            width={60}
                            tick={{ fill: 'var(--color-faint)', fontSize: 11 }}
                            axisLine={false}
                            tickLine={false}
                          />
                          <Tooltip
                            contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                            labelFormatter={(d) => new Date(String(d)).toLocaleString()}
                            formatter={(v) => [fmtPrice(Number(v), statCur), 'Equity']}
                          />
                          <Area
                            type="monotone"
                            dataKey="pnl"
                            stroke={s.total_pnl >= 0 ? 'var(--color-up)' : 'var(--color-down)'}
                            fill={s.total_pnl >= 0 ? 'var(--color-up)' : 'var(--color-down)'}
                            fillOpacity={0.12}
                            strokeWidth={1.75}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </CardBody>
                </Card>
              )}
              {s.by_setup.length > 0 && (
                <Card>
                  <CardHeader title="By setup" description="Which setups actually make money" />
                  <table className="w-full text-sm">
                    <thead className="border-y border-line text-xs text-muted">
                      <tr>
                        <th className="px-5 py-2 text-start font-medium">Setup</th>
                        <th className="px-3 py-2 text-end font-medium">Trades</th>
                        <th className="px-3 py-2 text-end font-medium">Win rate</th>
                        <th className="px-5 py-2 text-end font-medium">Net P&amp;L</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {s.by_setup.map((b) => (
                        <tr key={b.setup}>
                          <td className="px-5 py-2">{b.setup}</td>
                          <td className="tabular px-3 py-2 text-end">{b.trades}</td>
                          <td className="tabular px-3 py-2 text-end">{b.win_rate}%</td>
                          <td className={cx('tabular px-5 py-2 text-end', b.pnl >= 0 ? 'text-up' : 'text-down')}>
                            {fmtPrice(b.pnl, statCur)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}
            </>
          )}
        </div>
      </div>

      <Card className="overflow-hidden">
        <CardHeader title="Trades" description={data ? `${data.trades.length} shown` : undefined} />
        {data && data.trades.length === 0 ? (
          <EmptyState icon="pencil" title="No trades logged" description="Log one above, or from the Position size tab." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-y border-line text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 text-start font-medium">Date</th>
                  <th className="px-3 py-2 text-start font-medium">Stock</th>
                  <th className="px-3 py-2 text-end font-medium">Qty</th>
                  <th className="px-3 py-2 text-end font-medium">Entry</th>
                  <th className="px-3 py-2 text-end font-medium">Stop / target</th>
                  <th className="px-3 py-2 text-end font-medium">Exit</th>
                  <th className="px-3 py-2 text-end font-medium">P&amp;L</th>
                  <th className="px-3 py-2 text-end font-medium">R</th>
                  <th className="px-3 py-2 text-start font-medium">Setup</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(data?.trades ?? []).map((t) => {
                  const cur = CURRENCY[t.market]
                  const open = t.exit_price == null
                  return (
                    <tr key={t.id} className="align-top">
                      <td className="px-4 py-2 text-xs whitespace-nowrap text-muted">{new Date(t.entry_at).toLocaleDateString()}</td>
                      <td className="px-3 py-2">
                        <span className="font-mono font-medium">{t.symbol}</span>
                        <span className={cx('ms-1.5 text-[12px] font-medium uppercase', t.side === 'long' ? 'text-up' : 'text-down')}>
                          {t.side}
                        </span>
                        {t.notes && <div className="max-w-56 truncate text-xs text-muted" title={t.notes}>{t.notes}</div>}
                      </td>
                      <td className="tabular px-3 py-2 text-end">{num(t.quantity, t.quantity % 1 ? 4 : 0)}</td>
                      <td className="tabular px-3 py-2 text-end">{fmtPrice(t.entry_price, cur)}</td>
                      <td className="tabular px-3 py-2 text-end text-xs text-muted whitespace-nowrap">
                        {fmtPrice(t.stop, cur)} / {fmtPrice(t.target, cur)}
                      </td>
                      <td className="px-3 py-2 text-end">
                        {open ? (
                          <div className="flex justify-end gap-1">
                            <Input
                              type="number"
                              step="any"
                              value={closing[t.id] ?? ''}
                              onChange={(e) => setClosing((c) => ({ ...c, [t.id]: e.target.value }))}
                              onKeyDown={(e) => e.key === 'Enter' && close(t)}
                              placeholder="Exit"
                              className="w-24"
                            />
                            <Button size="sm" variant="secondary" disabled={!closing[t.id]} onClick={() => close(t)}>
                              Close
                            </Button>
                          </div>
                        ) : (
                          <span className="tabular">{fmtPrice(t.exit_price, cur)}</span>
                        )}
                      </td>
                      <td className={cx('tabular px-3 py-2 text-end', t.pnl != null && (t.pnl >= 0 ? 'text-up' : 'text-down'))}>
                        {open ? <span className="text-xs text-muted">open</span> : fmtPrice(t.pnl, cur)}
                        {t.fees > 0 && (
                          <div className="text-[12px] text-faint" title={t.fees_auto ? 'Estimated from the charges schedule' : 'Entered by you'}>
                            fees {fmtPrice(t.fees, cur)}
                            {t.fees_auto ? ' est.' : ''}
                          </div>
                        )}
                      </td>
                      <td className="tabular px-3 py-2 text-end">{t.r_multiple != null ? `${t.r_multiple}R` : '—'}</td>
                      <td className="px-3 py-2 text-xs text-muted">{t.setup || '—'}</td>
                      <td className="px-4 py-2 text-end">
                        <button
                          type="button"
                          onClick={() => remove(t)}
                          className="rounded-md p-1.5 text-faint hover:bg-down-soft hover:text-down"
                          aria-label={`Delete ${t.symbol} trade`}
                        >
                          <Icon name="trash" />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
