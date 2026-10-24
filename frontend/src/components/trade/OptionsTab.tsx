import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getOptionChain, getPayoff, type OptionChain, type OptionRow, type PayoffLeg, type PayoffResult } from '../../api/trade'
import { cx } from '../../lib/cx'
import { compact, errorMessage, num, price as fmtPrice } from '../../lib/format'
import { toast } from '../../lib/toast'
import { Alert, Button, Card, CardBody, CardHeader, EmptyState, Field, Icon, Input, Segmented, Select, Skeleton } from '../ui'
import { CURRENCY } from './shared'

const INDIA_INDICES = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50']
const STRIKES_AROUND = 12

type Preset = 'long_call' | 'long_put' | 'bull_call' | 'bear_put' | 'straddle' | 'strangle' | 'iron_condor' | 'covered_call'
const PRESETS: Array<{ value: Preset; label: string }> = [
  { value: 'long_call', label: 'Long call' },
  { value: 'long_put', label: 'Long put' },
  { value: 'bull_call', label: 'Bull call spread' },
  { value: 'bear_put', label: 'Bear put spread' },
  { value: 'straddle', label: 'Long straddle' },
  { value: 'strangle', label: 'Long strangle' },
  { value: 'iron_condor', label: 'Short iron condor' },
  { value: 'covered_call', label: 'Covered call' },
]

export default function OptionsTab({ symbol, market }: { symbol: string; market: string }) {
  const [optMarket, setOptMarket] = useState<'india' | 'us'>(market === 'us' || market === 'global' ? 'us' : 'india')
  const [sym, setSym] = useState(market === 'india' || market === 'us' || market === 'global' ? symbol : 'NIFTY')
  const [text, setText] = useState(sym)
  const [expiry, setExpiry] = useState<string | undefined>()
  const [chain, setChain] = useState<OptionChain | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [lot, setLot] = useState('1')
  const [legs, setLegs] = useState<PayoffLeg[]>([])
  const [payoff, setPayoff] = useState<PayoffResult | null>(null)
  const [oiView, setOiView] = useState<'oi' | 'chg'>('oi')

  useEffect(() => {
    setChain(null)
    setError(null)
    getOptionChain(sym, optMarket, expiry)
      .then((c) => {
        setChain(c)
        if (c.lot_size) setLot(String(c.lot_size))
      })
      .catch((err) => setError(errorMessage(err)))
  }, [sym, optMarket, expiry])

  useEffect(() => setLegs([]), [sym, expiry])

  const s = chain?.summary
  const cur = CURRENCY[optMarket]
  const rows = useMemo(() => {
    if (!chain || !s?.atm_strike) return chain?.rows ?? []
    if (showAll) return chain.rows
    const i = chain.rows.findIndex((r) => r.strike === s.atm_strike)
    return chain.rows.slice(Math.max(0, i - STRIKES_AROUND), i + STRIKES_AROUND + 1)
  }, [chain, s, showAll])

  // Payoff recalculates whenever the legs change.
  useEffect(() => {
    if (!legs.length || !s?.spot) {
      setPayoff(null)
      return
    }
    const t = window.setTimeout(() => {
      getPayoff({ legs, spot: s.spot, days: s.days_to_expiry, market: optMarket })
        .then(setPayoff)
        .catch((err) => toast.error(errorMessage(err)))
    }, 250)
    return () => window.clearTimeout(t)
  }, [legs, s, optMarket])

  const qty = Math.max(1, parseFloat(lot) || 1)

  function addLeg(row: OptionRow, type: 'call' | 'put', side: 'buy' | 'sell') {
    const leg = row[type]
    if (!leg?.ltp) return
    setLegs((l) => [...l, { type, side, strike: row.strike, premium: leg.ltp!, quantity: qty, iv: leg.iv }])
  }

  function applyPreset(p: Preset) {
    if (!chain || !s?.atm_strike) return
    const idx = chain.rows.findIndex((r) => r.strike === s.atm_strike)
    const at = (offset: number) => chain.rows[Math.min(chain.rows.length - 1, Math.max(0, idx + offset))]
    const mk = (row: OptionRow, type: 'call' | 'put', side: 'buy' | 'sell'): PayoffLeg => ({
      type,
      side,
      strike: row.strike,
      premium: row[type]?.ltp ?? 0,
      quantity: qty,
      iv: row[type]?.iv,
    })
    const atm = at(0)
    const next: Record<Preset, PayoffLeg[]> = {
      long_call: [mk(atm, 'call', 'buy')],
      long_put: [mk(atm, 'put', 'buy')],
      bull_call: [mk(atm, 'call', 'buy'), mk(at(3), 'call', 'sell')],
      bear_put: [mk(atm, 'put', 'buy'), mk(at(-3), 'put', 'sell')],
      straddle: [mk(atm, 'call', 'buy'), mk(atm, 'put', 'buy')],
      strangle: [mk(at(2), 'call', 'buy'), mk(at(-2), 'put', 'buy')],
      iron_condor: [mk(at(-4), 'put', 'buy'), mk(at(-2), 'put', 'sell'), mk(at(2), 'call', 'sell'), mk(at(4), 'call', 'buy')],
      covered_call: [
        { type: 'stock', side: 'buy', strike: 0, premium: s.spot, quantity: qty },
        mk(at(2), 'call', 'sell'),
      ],
    }
    setLegs(next[p])
  }

  const oiData = rows.map((r) => ({
    strike: r.strike,
    call: oiView === 'oi' ? (r.call?.oi ?? 0) : (r.call?.chg_oi ?? 0),
    put: oiView === 'oi' ? (r.put?.oi ?? 0) : (r.put?.chg_oi ?? 0),
  }))

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <Segmented
          options={[
            { value: 'india', label: 'India (NSE)' },
            { value: 'us', label: 'US' },
          ]}
          value={optMarket}
          onChange={(v) => {
            const next = v as 'india' | 'us'
            const fresh = next === 'india' ? 'NIFTY' : 'SPY'
            setOptMarket(next)
            setExpiry(undefined)
            setText(fresh)
            setSym(fresh)
          }}
          size="sm"
        />
        <div className="flex gap-2">
          <Input
            value={text}
            onChange={(e) => setText(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && text.trim() && (setExpiry(undefined), setSym(text.trim()))}
            className="w-40"
            placeholder={optMarket === 'india' ? 'NIFTY, RELIANCE' : 'AAPL, SPY'}
          />
          <Button variant="secondary" onClick={() => text.trim() && (setExpiry(undefined), setSym(text.trim()))}>
            Load
          </Button>
        </div>
        {optMarket === 'india' && (
          <div className="flex flex-wrap gap-1.5">
            {INDIA_INDICES.map((i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  setText(i)
                  setExpiry(undefined)
                  setSym(i)
                }}
                className={cx(
                  'rounded-full border px-2.5 py-0.5 text-xs font-medium',
                  sym === i ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:text-fg',
                )}
              >
                {i}
              </button>
            ))}
          </div>
        )}
        {chain && (
          <Select
            className="w-40"
            options={chain.expiries.map((e) => ({ value: e, label: e }))}
            value={s?.expiry ?? ''}
            onChange={(e) => setExpiry(e.target.value)}
          />
        )}
        <span className="text-xs text-muted">
          {optMarket === 'india' ? 'NSE option chain' : 'US option chain (market data feed)'}
          {chain?.timestamp && ` · ${chain.timestamp}`}
        </span>
      </div>

      {error ? (
        <Alert tone="warn" title="Option chain unavailable">
          {error}
          {' '}Options are available for NSE indices and F&amp;O stocks, and for US listed symbols.
        </Alert>
      ) : !chain || !s ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4 lg:grid-cols-8">
            <Tile label="Spot" value={fmtPrice(s.spot, cur)} />
            <Tile label="Days to expiry" value={String(s.days_to_expiry)} />
            <Tile label="ATM IV" value={s.atm_iv != null ? `${s.atm_iv}%` : '—'} />
            <Tile label="Expected move" value={s.expected_move != null ? `±${num(s.expected_move)}` : '—'} sub="1 sd to expiry" />
            <Tile label="PCR (OI)" value={num(s.pcr_oi)} sub={s.pcr_oi == null ? undefined : s.pcr_oi > 1.2 ? 'put-heavy' : s.pcr_oi < 0.7 ? 'call-heavy' : 'balanced'} />
            <Tile label="Max pain" value={s.max_pain != null ? num(s.max_pain, 0) : '—'} />
            <Tile label="Support (put OI)" value={s.support != null ? num(s.support, 0) : '—'} tone="up" />
            <Tile label="Resistance (call OI)" value={s.resistance != null ? num(s.resistance, 0) : '—'} tone="down" />
          </div>

          {chain.vol_compare && <VolCompare v={chain.vol_compare} />}

          <div className="grid gap-6 xl:grid-cols-2">
            {chain.gex && <GammaCard gex={chain.gex} spot={s.spot} india={optMarket === 'india'} />}
            <SmileCard smile={chain.smile ?? null} atm={s.atm_strike} />
          </div>

          <Card>
            <CardHeader
              title="Open interest by strike"
              actions={
                optMarket === 'india' ? (
                  <Segmented
                    options={[
                      { value: 'oi', label: 'OI' },
                      { value: 'chg', label: 'Change in OI' },
                    ]}
                    value={oiView}
                    onChange={(v) => setOiView(v as 'oi' | 'chg')}
                    size="sm"
                  />
                ) : undefined
              }
            />
            <CardBody>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={oiData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="var(--color-line)" vertical={false} />
                    <XAxis dataKey="strike" tick={{ fill: 'var(--color-faint)', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={16} />
                    <YAxis orientation="right" width={56} tickFormatter={(v: number) => compact(v)} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }} formatter={(v, n) => [compact(Number(v)), n === 'call' ? 'Calls' : 'Puts']} />
                    <Legend formatter={(v) => (v === 'call' ? 'Calls' : 'Puts')} wrapperStyle={{ fontSize: 12 }} />
                    {s.atm_strike != null && <ReferenceLine x={s.atm_strike} stroke="var(--color-faint)" strokeDasharray="3 3" />}
                    <Bar dataKey="call" fill="var(--color-down)" fillOpacity={0.75} />
                    <Bar dataKey="put" fill="var(--color-up)" fillOpacity={0.75} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardBody>
          </Card>

          <div className="grid gap-6 2xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Card className="overflow-hidden">
              <CardHeader
                title="Option chain"
                description="Shaded = in the money. Click B / S to add a leg to the strategy."
                actions={
                  <button type="button" className="text-xs text-muted hover:text-fg" onClick={() => setShowAll((v) => !v)}>
                    {showAll ? `Near ATM only` : `All ${chain.rows.length} strikes`}
                  </button>
                }
              />
              <div className="max-h-[32rem] overflow-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 z-10 border-y border-line bg-surface text-muted">
                    <tr>
                      <th className="px-2 py-1.5 text-end font-medium">OI</th>
                      {optMarket === 'india' && <th className="px-2 py-1.5 text-end font-medium">Chg OI</th>}
                      <th className="px-2 py-1.5 text-end font-medium">IV</th>
                      <th className="px-2 py-1.5 text-end font-medium">Δ</th>
                      <th className="px-2 py-1.5 text-end font-medium">Call LTP</th>
                      <th className="bg-raised px-2 py-1.5 text-center font-semibold text-fg">Strike</th>
                      <th className="px-2 py-1.5 text-start font-medium">Put LTP</th>
                      <th className="px-2 py-1.5 text-start font-medium">Δ</th>
                      <th className="px-2 py-1.5 text-start font-medium">IV</th>
                      {optMarket === 'india' && <th className="px-2 py-1.5 text-start font-medium">Chg OI</th>}
                      <th className="px-2 py-1.5 text-start font-medium">OI</th>
                    </tr>
                  </thead>
                  <tbody className="tabular divide-y divide-line">
                    {rows.map((r) => {
                      const callItm = r.strike < s.spot
                      const atm = r.strike === s.atm_strike
                      return (
                        <tr key={r.strike} className={cx(atm && 'outline outline-1 -outline-offset-1 outline-accent')}>
                          <td className={cx('px-2 py-1 text-end', callItm && 'bg-down-soft/40')}>{compact(r.call?.oi ?? null)}</td>
                          {optMarket === 'india' && (
                            <td className={cx('px-2 py-1 text-end', callItm && 'bg-down-soft/40', (r.call?.chg_oi ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                              {compact(r.call?.chg_oi ?? null)}
                            </td>
                          )}
                          <td className={cx('px-2 py-1 text-end', callItm && 'bg-down-soft/40')} title={r.call?.iv_estimated ? 'Estimated from the price' : undefined}>
                            {num(r.call?.iv, 1)}
                          </td>
                          <td className={cx('px-2 py-1 text-end text-muted', callItm && 'bg-down-soft/40')}>{num(r.call?.delta, 2)}</td>
                          <td className={cx('px-2 py-1 text-end', callItm && 'bg-down-soft/40')}>
                            <LegButtons ltp={r.call?.ltp} onAdd={(side) => addLeg(r, 'call', side)} align="right" />
                          </td>
                          <td className="bg-raised px-2 py-1 text-center font-semibold">{num(r.strike, r.strike % 1 ? 1 : 0)}</td>
                          <td className={cx('px-2 py-1', !callItm && 'bg-up-soft/40')}>
                            <LegButtons ltp={r.put?.ltp} onAdd={(side) => addLeg(r, 'put', side)} align="left" />
                          </td>
                          <td className={cx('px-2 py-1 text-muted', !callItm && 'bg-up-soft/40')}>{num(r.put?.delta, 2)}</td>
                          <td className={cx('px-2 py-1', !callItm && 'bg-up-soft/40')} title={r.put?.iv_estimated ? 'Estimated from the price' : undefined}>
                            {num(r.put?.iv, 1)}
                          </td>
                          {optMarket === 'india' && (
                            <td className={cx('px-2 py-1', !callItm && 'bg-up-soft/40', (r.put?.chg_oi ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                              {compact(r.put?.chg_oi ?? null)}
                            </td>
                          )}
                          <td className={cx('px-2 py-1', !callItm && 'bg-up-soft/40')}>{compact(r.put?.oi ?? null)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card>
              <CardHeader title="Strategy builder" description="Payoff at expiry and today (Black-Scholes)." />
              <CardBody className="space-y-4">
                <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-2">
                  <Field label="Preset">
                    <Select
                      options={[{ value: '', label: 'Choose a strategy…' }, ...PRESETS]}
                      value=""
                      onChange={(e) => e.target.value && applyPreset(e.target.value as Preset)}
                    />
                  </Field>
                  <Field label={optMarket === 'india' ? 'Lot size' : 'Contract ×'} hint={optMarket === 'india' ? 'Verify with your broker' : undefined}>
                    <Input type="number" min="1" value={lot} onChange={(e) => setLot(e.target.value)} />
                  </Field>
                </div>
                {legs.length === 0 ? (
                  <EmptyState icon="plus" title="No legs" description="Pick a preset or click B / S in the chain." />
                ) : (
                  <ul className="divide-y divide-line rounded-lg border border-line text-sm">
                    {legs.map((l, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-2 px-3 py-1.5">
                        <button
                          type="button"
                          onClick={() => setLegs((all) => all.map((x, j) => (j === i ? { ...x, side: x.side === 'buy' ? 'sell' : 'buy' } : x)))}
                          className={cx('w-10 rounded px-1 text-xs font-semibold uppercase', l.side === 'buy' ? 'bg-up-soft text-up' : 'bg-down-soft text-down')}
                          title="Switch buy / sell"
                        >
                          {l.side}
                        </button>
                        <span className="w-24 text-xs">
                          {l.type === 'stock' ? 'Underlying' : `${num(l.strike, l.strike % 1 ? 1 : 0)} ${l.type.toUpperCase()}`}
                        </span>
                        <Input
                          type="number"
                          step="any"
                          value={l.premium}
                          onChange={(e) => setLegs((all) => all.map((x, j) => (j === i ? { ...x, premium: parseFloat(e.target.value) || 0 } : x)))}
                          className="w-24"
                          aria-label="Premium"
                        />
                        <span className="text-xs text-muted">×</span>
                        <Input
                          type="number"
                          min="1"
                          value={l.quantity}
                          onChange={(e) => setLegs((all) => all.map((x, j) => (j === i ? { ...x, quantity: parseFloat(e.target.value) || 1 } : x)))}
                          className="w-20"
                          aria-label="Quantity"
                        />
                        <button
                          type="button"
                          onClick={() => setLegs((all) => all.filter((_, j) => j !== i))}
                          className="ms-auto rounded-md p-1 text-faint hover:bg-down-soft hover:text-down"
                          aria-label="Remove leg"
                        >
                          <Icon name="x" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                {payoff && (
                  <>
                    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line">
                      <Tile label={payoff.net_premium >= 0 ? 'Net credit' : 'Net debit'} value={fmtPrice(Math.abs(payoff.net_premium), cur)} />
                      <Tile label="Breakeven" value={payoff.breakevens.length ? payoff.breakevens.map((b) => num(b)).join(' / ') : '—'} />
                      <Tile label="Max profit" value={payoff.max_profit == null ? 'Unlimited' : fmtPrice(payoff.max_profit, cur)} tone="up" />
                      <Tile label="Max loss" value={payoff.max_loss == null ? 'Unlimited' : fmtPrice(payoff.max_loss, cur)} tone="down" />
                    </div>
                    <div className="h-56">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={payoff.points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                          <CartesianGrid stroke="var(--color-line)" vertical={false} />
                          <XAxis dataKey="price" type="number" domain={['dataMin', 'dataMax']} tickFormatter={(v: number) => num(v, 0)} tick={{ fill: 'var(--color-faint)', fontSize: 10 }} axisLine={false} tickLine={false} />
                          <YAxis orientation="right" width={60} tickFormatter={(v: number) => compact(v)} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                          <Tooltip contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }} labelFormatter={(v) => `At ${num(Number(v))}`} formatter={(v, n) => [fmtPrice(Number(v), cur), n === 'expiry' ? 'At expiry' : 'Today']} />
                          <ReferenceLine y={0} stroke="var(--color-line-strong)" />
                          <ReferenceLine x={s.spot} stroke="var(--color-accent)" strokeDasharray="3 3" label={{ value: 'spot', fill: 'var(--color-faint)', fontSize: 10, position: 'top' }} />
                          <Line type="linear" dataKey="expiry" stroke="var(--color-fg)" dot={false} strokeWidth={1.75} />
                          <Line type="monotone" dataKey="today" stroke="var(--color-accent)" dot={false} strokeWidth={1.25} strokeDasharray="4 3" />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="grid grid-cols-4 gap-2 text-center text-xs">
                      {(['delta', 'gamma', 'theta', 'vega'] as const).map((g) => (
                        <div key={g} className="rounded-md border border-line px-2 py-1.5">
                          <div className="text-muted capitalize">{g}</div>
                          <div className="tabular font-medium">{num(payoff.greeks[g], g === 'gamma' ? 4 : 2)}</div>
                        </div>
                      ))}
                    </div>
                    <p className="text-[12px] text-faint">Theta is per day and vega per 1 IV point, for the whole position. Taxes and brokerage aren't included.</p>
                  </>
                )}
              </CardBody>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

function LegButtons({ ltp, onAdd, align }: { ltp: number | null | undefined; onAdd: (side: 'buy' | 'sell') => void; align: 'left' | 'right' }) {
  if (ltp == null) return <span className="text-faint">—</span>
  return (
    <span className={cx('group inline-flex items-center gap-1', align === 'right' && 'flex-row-reverse')}>
      <span className="font-medium">{num(ltp)}</span>
      <span className="flex gap-0.5 opacity-40 group-hover:opacity-100">
        <button type="button" onClick={() => onAdd('buy')} className="rounded bg-up-soft px-1 text-[11px] font-bold text-up" aria-label="Buy">
          B
        </button>
        <button type="button" onClick={() => onAdd('sell')} className="rounded bg-down-soft px-1 text-[11px] font-bold text-down" aria-label="Sell">
          S
        </button>
      </span>
    </span>
  )
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'up' | 'down' }) {
  return (
    <div className="bg-surface px-3 py-2.5">
      <div className="text-[12px] text-muted">{label}</div>
      <div className={cx('tabular text-sm font-semibold', tone === 'up' && 'text-up', tone === 'down' && 'text-down')}>{value}</div>
      {sub && <div className="text-[12px] text-faint">{sub}</div>}
    </div>
  )
}

const VERDICT = {
  expensive: { label: 'Options look expensive', tone: 'text-down', hint: 'Implied volatility is well above what the stock has actually been doing. Premium sellers are paid more; option buyers need a bigger move to profit. Check for an event (results, budget) that could justify it.' },
  cheap: { label: 'Options look cheap', tone: 'text-up', hint: 'Implied volatility is below recent realized volatility. Buying options costs less than the stock has been moving; selling premium pays little.' },
  fair: { label: 'Options priced near recent movement', tone: 'text-fg', hint: 'Implied volatility is close to realized volatility - no clear edge for buyers or sellers from volatility alone.' },
} as const

/** Is the option market pricing more or less movement than the stock has shown? */
function VolCompare({ v }: { v: NonNullable<OptionChain['vol_compare']> }) {
  const verdict = v.verdict ? VERDICT[v.verdict] : null
  const max = Math.max(v.rv_20_high, v.atm_iv ?? 0, v.rv_20) * 1.15
  const x = (n: number) => `${(n / max) * 100}%`
  return (
    <Card>
      <CardHeader title="Implied vs realized volatility" description="What options are pricing in, against how much the underlying has really been moving" />
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className={cx('text-sm font-semibold', verdict?.tone)}>{verdict ? verdict.label : 'No ATM implied volatility for this expiry'}</div>
          {v.ratio != null && <div className="tabular text-sm text-muted">IV / RV = {num(v.ratio)}×</div>}
        </div>
        <div className="relative h-8">
          <div className="absolute top-3 h-2 w-full rounded-full bg-raised" />
          <div className="absolute top-3 h-2 rounded-full bg-accent/30" style={{ left: x(v.rv_20_low), width: `calc(${x(v.rv_20_high)} - ${x(v.rv_20_low)})` }}
            title="Usual range of 20-day realized volatility over the past year (10th-90th percentile)" />
          <div className="absolute top-1.5 h-5 w-1 rounded-full bg-fg" style={{ left: `calc(${x(v.rv_20)} - 2px)` }} title={`Realized (20d) ${v.rv_20}%`} />
          {v.atm_iv != null && (
            <div className="absolute top-1 h-6 w-1.5 rounded-full bg-warn" style={{ left: `calc(${x(v.atm_iv)} - 3px)` }} title={`ATM implied ${v.atm_iv}%`} />
          )}
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          <span><span className="me-1 inline-block h-2 w-2 rounded-full bg-warn" />ATM IV {v.atm_iv != null ? `${v.atm_iv}%` : '—'}</span>
          <span><span className="me-1 inline-block h-2 w-2 rounded-full bg-fg" />Realized 20d {v.rv_20}%</span>
          <span>Realized 60d {v.rv_60 != null ? `${v.rv_60}%` : '—'}</span>
          <span><span className="me-1 inline-block h-2 w-2 rounded-full bg-accent/40" />Usual 20d range {v.rv_20_low}-{v.rv_20_high}%</span>
        </div>
        {verdict && <p className="text-xs text-faint">{verdict.hint}</p>}
      </CardBody>
    </Card>
  )
}

const TIP = { background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }
const near = (strike: number, spot: number) => Math.abs(strike / spot - 1) <= 0.1

/** Dealer gamma by strike under the usual convention (dealers long calls, short puts). */
function GammaCard({ gex, spot, india }: { gex: NonNullable<OptionChain['gex']>; spot: number; india: boolean }) {
  const data = gex.by_strike.filter((d) => near(d.strike, spot))
  const positive = gex.total >= 0
  // ₹ crore for India, $ with K/M/B elsewhere
  const money = (v: number) =>
    india ? `₹${(v / 1e7).toLocaleString('en-IN', { maximumFractionDigits: Math.abs(v) >= 1e9 ? 0 : 1 })} cr` : `$${compact(v)}`
  return (
    <Card>
      <CardHeader title="Gamma exposure by strike" description="Estimated dealer gamma, per 1% move of the underlying" />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div>
            <div className="text-xs text-muted">Net gamma</div>
            <div className={cx('tabular font-semibold', positive ? 'text-up' : 'text-down')}>{money(gex.total)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">Zero-gamma level</div>
            <div className="tabular font-semibold">{gex.zero_gamma != null ? num(gex.zero_gamma, 0) : '—'}</div>
          </div>
          <div>
            <div className="text-xs text-muted">Largest at strike</div>
            <div className="tabular font-semibold">{gex.peak_strike != null ? num(gex.peak_strike, 0) : '—'}</div>
          </div>
        </div>
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--color-line)" vertical={false} />
              <XAxis dataKey="strike" tick={{ fill: 'var(--color-faint)', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={16} />
              <YAxis orientation="right" width={india ? 72 : 56} tickFormatter={(v: number) => money(v)} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={TIP} formatter={(v) => [money(Number(v)), 'Net gamma per 1%']} />
              <ReferenceLine y={0} stroke="var(--color-line-strong)" />
              <ReferenceLine x={data.reduce((b, d) => (Math.abs(d.strike - spot) < Math.abs(b - spot) ? d.strike : b), data[0]?.strike ?? spot)} stroke="var(--color-faint)" strokeDasharray="3 3" />
              <Bar dataKey="net" fill="var(--color-accent)" fillOpacity={0.8} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="text-[12px] text-faint">
          {positive
            ? 'Net positive: under this convention dealers hedge against moves (sell rallies, buy dips), which tends to damp swings.'
            : 'Net negative: under this convention dealers hedge with moves (sell into falls, buy into rallies), which can widen swings.'}{' '}
          Gamma x open interest x contract size ({num(gex.multiplier, 0)}) x spot² x 1%; calls counted positive, puts negative, as public
          gamma estimates assume. Real dealer positions are not published, so this is an estimate.
          {gex.interpolated_iv && ' Strikes with no solvable IV use their neighbours\' IV.'} Dashed line: spot.
        </p>
      </CardBody>
    </Card>
  )
}

/** Implied volatility across strikes for this expiry. */
function SmileCard({ smile, atm }: { smile: OptionChain['smile'] | null; atm: number | null }) {
  const data = smile?.points ?? []
  return (
    <Card>
      <CardHeader title="Volatility smile" description="Implied volatility by strike for this expiry" />
      <CardBody className="space-y-3">
        {smile?.same_day && (
          <p className="text-xs text-warn">Expires today: with only hours left, implied volatilities jump around. A later expiry gives a steadier picture.</p>
        )}
        {data.length < 3 ? (
          <p className="text-sm text-muted">Too few strikes with an implied volatility for this expiry.</p>
        ) : (
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--color-line)" vertical={false} />
                <XAxis dataKey="strike" tick={{ fill: 'var(--color-faint)', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={16} />
                <YAxis orientation="right" width={44} domain={['auto', 'auto']} tickFormatter={(v: number) => `${v}%`} tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TIP} formatter={(v) => [`${num(Number(v))}%`, 'Implied volatility']} />
                {atm != null && <ReferenceLine x={atm} stroke="var(--color-faint)" strokeDasharray="3 3" />}
                <Line type="monotone" dataKey="iv" stroke="var(--color-accent)" dot={{ r: 1.5 }} strokeWidth={1.8} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        <p className="text-[12px] text-faint">
          Out-of-the-money options (puts below the forward, calls above), each IV solved against the forward level implied by put-call parity
          {smile?.forward != null && ` (${num(smile.forward)})`}, so calls and puts agree. Higher IV on low strikes than on high ones (a skew)
          means protection against falls costs more than bets on rises. Dashed line: the at-the-money strike. Strikes within 10%.
        </p>
      </CardBody>
    </Card>
  )
}
