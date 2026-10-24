import { useEffect, useMemo, useState } from 'react'
import { getQuote } from '../../api/stocks'
import { createAlert, estimateCharges, getLotSize, type Charges, type Product } from '../../api/trade'
import { cx } from '../../lib/cx'
import { errorMessage, num, price as fmtPrice } from '../../lib/format'
import { toast } from '../../lib/toast'
import { Alert, Button, Card, CardBody, CardHeader, Field, Input, Segmented } from '../ui'
import { CURRENCY } from './shared'

export interface TradePlan {
  entry?: number
  stop?: number
  target?: number
}

type Side = 'long' | 'short'

const PREFS_KEY = 'marketmyna.sizer'
const INDIA_PRODUCTS = [
  { value: 'intraday', label: 'Intraday' },
  { value: 'delivery', label: 'Delivery' },
  { value: 'futures', label: 'Futures' },
  { value: 'options', label: 'Options' },
]

function loadPrefs() {
  const fallback = { capital: '100000', riskPct: '1', leverage: '1', product: 'intraday' as Product, pct: '0', flat: '0' }
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}') }
  } catch {
    return fallback
  }
}

export default function SizerTab({
  symbol,
  market,
  plan,
  onLog,
}: {
  symbol: string
  market: string
  plan: TradePlan | null
  onLog: (trade: { side: Side; quantity: number; entry: number; stop: number; target?: number; product?: Product }) => void
}) {
  const [prefs, setPrefs] = useState(loadPrefs)
  const [side, setSide] = useState<Side>('long')
  const [entry, setEntry] = useState('')
  const [stop, setStop] = useState('')
  const [target, setTarget] = useState('')
  const cur = CURRENCY[market]
  const india = market === 'india'
  const fractional = market === 'crypto'
  const derivative = india && (prefs.product === 'futures' || prefs.product === 'options')
  const [lot, setLot] = useState('')
  const [chargesAt, setChargesAt] = useState<{ stop: Charges | null; target: Charges | null }>({ stop: null, target: null })

  // F&O quantities come in exchange lots.
  useEffect(() => {
    setLot('')
    if (!derivative) return
    getLotSize(symbol)
      .then((l) => l && setLot(String(l)))
      .catch(() => {})
  }, [symbol, derivative])

  function setPref(patch: Partial<typeof prefs>) {
    setPrefs((p: typeof prefs) => {
      const next = { ...p, ...patch }
      try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(next))
      } catch {
        // not remembered
      }
      return next
    })
  }

  // A plan from the chart wins; otherwise start from the live price.
  useEffect(() => {
    if (plan) {
      if (plan.entry) setEntry(plan.entry.toFixed(2))
      if (plan.stop) setStop(plan.stop.toFixed(2))
      if (plan.target) setTarget(plan.target.toFixed(2))
      if (plan.entry && plan.stop) setSide(plan.stop < plan.entry ? 'long' : 'short')
      return
    }
    setEntry('')
    setStop('')
    setTarget('')
    getQuote(symbol, market)
      .then((q) => q.price && setEntry(q.price.toFixed(2)))
      .catch(() => {})
  }, [symbol, market, plan])

  const r = useMemo(() => {
    const capital = parseFloat(prefs.capital)
    const riskPct = parseFloat(prefs.riskPct)
    const leverage = Math.max(1, parseFloat(prefs.leverage) || 1)
    const e = parseFloat(entry)
    const s = parseFloat(stop)
    const t = parseFloat(target)
    if (![capital, riskPct, e, s].every(Number.isFinite) || capital <= 0 || e <= 0) return null
    const perShare = side === 'long' ? e - s : s - e
    if (perShare <= 0) return { error: side === 'long' ? 'For a long trade the stop must be below entry.' : 'For a short trade the stop must be above entry.' }
    const riskBudget = (capital * riskPct) / 100
    const lotSize = derivative ? Math.max(1, parseInt(lot, 10) || 1) : 1
    const round = (q: number) => (fractional ? Math.floor(q * 1e6) / 1e6 : Math.floor(q / lotSize) * lotSize)
    const byRisk = round(riskBudget / perShare)
    const byCapital = round((capital * leverage) / e)
    const qty = Math.min(byRisk, byCapital)
    const hasTarget = Number.isFinite(t) && (side === 'long' ? t > e : t < e)
    return {
      qty,
      lotSize,
      limitedByCapital: byCapital < byRisk,
      value: qty * e,
      riskBudget,
      perShare,
      grossLoss: (side === 'long' ? s - e : e - s) * qty,
      grossProfit: hasTarget ? (side === 'long' ? t - e : e - t) * qty : null,
      rr: hasTarget ? Math.abs(t - e) / perShare : null,
      pctCapital: ((qty * e) / capital) * 100,
      target: hasTarget ? t : null,
      entry: e,
      stop: s,
    }
  }, [prefs, entry, stop, target, side, fractional, derivative, lot])

  // Round-trip charges from the server's schedule, at the stop and at the target.
  const sized = r && !('error' in r) ? r : null
  useEffect(() => {
    if (!sized || !sized.qty) {
      setChargesAt({ stop: null, target: null })
      return
    }
    const at = (exit: number) =>
      estimateCharges({
        market,
        product: india ? prefs.product : undefined,
        buy_value: (side === 'long' ? sized.entry : exit) * sized.qty,
        sell_value: (side === 'long' ? exit : sized.entry) * sized.qty,
        quantity: sized.qty,
        commission_pct: parseFloat(prefs.pct) || 0,
        flat: parseFloat(prefs.flat) || 0,
      })
    const id = window.setTimeout(() => {
      Promise.all([at(sized.stop), sized.target != null ? at(sized.target) : Promise.resolve(null)])
        .then(([stopC, targetC]) => setChargesAt({ stop: stopC, target: targetC }))
        .catch(() => setChargesAt({ stop: null, target: null }))
    }, 250)
    return () => window.clearTimeout(id)
  }, [sized?.qty, sized?.entry, sized?.stop, sized?.target, side, market, india, prefs.product, prefs.pct, prefs.flat]) // eslint-disable-line react-hooks/exhaustive-deps

  async function alertsForPlan() {
    if (!r || 'error' in r) return
    try {
      await createAlert({
        symbol,
        market,
        kind: side === 'long' ? 'price_below' : 'price_above',
        value: r.stop,
        note: `Stop for ${num(r.qty, fractional ? 4 : 0)} ${symbol}`,
      })
      if (r.target)
        await createAlert({
          symbol,
          market,
          kind: side === 'long' ? 'price_above' : 'price_below',
          value: r.target,
          note: `Target for ${num(r.qty, fractional ? 4 : 0)} ${symbol}`,
        })
      toast.success(r.target ? 'Stop and target alerts set' : 'Stop alert set')
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const ok = sized
  const charges = chargesAt.target ?? chargesAt.stop
  const loss = ok && chargesAt.stop ? ok.grossLoss - chargesAt.stop.total : null
  const profit = ok && ok.grossProfit != null && chargesAt.target ? ok.grossProfit - chargesAt.target.total : null
  const breakeven = ok && ok.qty && chargesAt.stop ? ok.entry + ((side === 'long' ? 1 : -1) * chargesAt.stop.total) / ok.qty : null

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title="Position size" description={`${symbol} · risk-based sizing`} />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Segmented
              options={[
                { value: 'long', label: 'Long (buy)' },
                { value: 'short', label: 'Short (sell)' },
              ]}
              value={side}
              onChange={(v) => setSide(v as Side)}
              size="sm"
            />
            {india && (
              <Segmented
                options={INDIA_PRODUCTS}
                value={prefs.product}
                onChange={(v) => setPref({ product: v as Product })}
                size="sm"
              />
            )}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Field label={`Capital (${cur})`}>
              <Input type="number" value={prefs.capital} onChange={(e) => setPref({ capital: e.target.value })} />
            </Field>
            <Field label="Risk per trade %">
              <Input type="number" step="0.1" value={prefs.riskPct} onChange={(e) => setPref({ riskPct: e.target.value })} />
            </Field>
            <Field label="Leverage ×">
              <Input type="number" step="0.5" min="1" value={prefs.leverage} onChange={(e) => setPref({ leverage: e.target.value })} />
            </Field>
            <Field label="Entry">
              <Input type="number" step="any" value={entry} onChange={(e) => setEntry(e.target.value)} />
            </Field>
            <Field label="Stop loss">
              <Input type="number" step="any" value={stop} onChange={(e) => setStop(e.target.value)} />
            </Field>
            <Field label="Target (optional)">
              <Input type="number" step="any" value={target} onChange={(e) => setTarget(e.target.value)} />
            </Field>
            {derivative && (
              <Field label="Lot size" hint="From the exchange's current instrument list">
                <Input type="number" min="1" value={lot} onChange={(e) => setLot(e.target.value)} />
              </Field>
            )}
          </div>
          {prefs.product === 'options' && india && (
            <p className="text-xs text-muted">For options, enter the premium as entry, stop and target.</p>
          )}
          {!india && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Commission % per side">
                <Input type="number" step="0.01" value={prefs.pct} onChange={(e) => setPref({ pct: e.target.value })} />
              </Field>
              <Field label={`Flat fee per order (${cur})`}>
                <Input type="number" step="0.01" value={prefs.flat} onChange={(e) => setPref({ flat: e.target.value })} />
              </Field>
            </div>
          )}
          <p className="text-xs text-muted">
            Quantity = (capital × risk %) ÷ (entry − stop), capped by capital × leverage{derivative ? ', in whole lots' : ''}.
            {india && ' Charges use a discount-broker schedule (STT, exchange, SEBI, stamp duty, GST); your contract note is final.'}
            {(market === 'us' || market === 'global') && ' US charges include the SEC fee and FINRA TAF on sells.'}
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Result" />
        <CardBody className="space-y-4">
          {r && 'error' in r ? (
            <Alert tone="warn" title="Check the stop">{r.error}</Alert>
          ) : !ok ? (
            <p className="text-sm text-muted">Enter capital, risk, entry and stop.</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3">
                <Tile
                  label="Quantity"
                  value={num(ok.qty, fractional ? 4 : 0)}
                  sub={derivative && ok.lotSize > 1 ? `${ok.qty / ok.lotSize} lot${ok.qty / ok.lotSize === 1 ? '' : 's'} of ${ok.lotSize}` : undefined}
                  big
                />
                <Tile label="Position value" value={fmtPrice(ok.value, cur)} sub={`${ok.pctCapital.toFixed(1)}% of capital`} />
                <Tile label="Risk budget" value={fmtPrice(ok.riskBudget, cur)} sub={`${fmtPrice(ok.perShare, cur)} per unit`} />
                <Tile label="Loss at stop" value={fmtPrice(loss ?? ok.grossLoss, cur)} tone="down" sub={loss != null ? 'after charges' : 'before charges'} />
                <Tile
                  label="Profit at target"
                  value={profit != null ? fmtPrice(profit, cur) : ok.grossProfit != null ? fmtPrice(ok.grossProfit, cur) : '—'}
                  tone={(profit ?? ok.grossProfit ?? 0) > 0 ? 'up' : undefined}
                  sub={profit != null ? 'after charges' : ok.grossProfit != null ? 'before charges' : undefined}
                />
                <Tile
                  label="Reward : risk"
                  value={ok.rr != null ? `${ok.rr.toFixed(2)} : 1` : '—'}
                  tone={ok.rr != null ? (ok.rr >= 2 ? 'up' : ok.rr < 1 ? 'down' : undefined) : undefined}
                />
              </div>
              {ok.limitedByCapital && (
                <p className="text-xs text-warn">Limited by capital × leverage: the full risk budget isn't used.</p>
              )}
              {ok.qty === 0 && (
                <p className="text-xs text-warn">
                  Risk budget is smaller than one {derivative ? 'lot' : 'unit'}'s risk; widen risk % or tighten the stop.
                </p>
              )}
              {charges && (
              <div>
                <span className="mb-1.5 block text-xs font-medium text-muted">
                  Charges ({chargesAt.target ? 'round trip at target' : 'round trip at stop'}, rates {charges.rates_as_of})
                </span>
                <ul className="divide-y divide-line rounded-lg border border-line text-sm">
                  {Object.entries(charges.parts)
                    .filter(([, v]) => v > 0.004)
                    .map(([k, v]) => (
                      <li key={k} className="flex justify-between px-3 py-1.5">
                        <span className="text-muted">{k}</span>
                        <span className="tabular">{fmtPrice(v, cur)}</span>
                      </li>
                    ))}
                  <li className="flex justify-between px-3 py-1.5 font-medium">
                    <span>Total</span>
                    <span className="tabular">{fmtPrice(charges.total, cur)}</span>
                  </li>
                </ul>
                {breakeven != null && (
                  <p className="mt-1.5 text-xs text-muted">Breakeven after charges: {fmtPrice(breakeven, cur)}</p>
                )}
              </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={!ok.qty}
                  onClick={() =>
                    onLog({
                      side,
                      quantity: ok.qty,
                      entry: ok.entry,
                      stop: ok.stop,
                      target: ok.target ?? undefined,
                      product: india ? prefs.product : undefined,
                    })
                  }
                >
                  Log in journal
                </Button>
                <Button size="sm" variant="secondary" icon="bell" onClick={alertsForPlan}>
                  Alerts at stop{ok.target ? ' & target' : ''}
                </Button>
              </div>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

function Tile({ label, value, sub, tone, big }: { label: string; value: string; sub?: string; tone?: 'up' | 'down'; big?: boolean }) {
  return (
    <div className="bg-surface px-3 py-2.5">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx('tabular font-semibold', big ? 'text-xl' : 'text-sm', tone === 'up' && 'text-up', tone === 'down' && 'text-down')}>
        {value}
      </div>
      {sub && <div className="text-[12px] text-faint">{sub}</div>}
    </div>
  )
}
