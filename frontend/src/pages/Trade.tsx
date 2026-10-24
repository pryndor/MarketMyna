import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { searchListings } from '../api/listings'
import { getRisk, listAlerts, type PriceAlert, type RiskStatus } from '../api/trade'
import SymbolSearch from '../components/SymbolSearch'
import AlertsTab from '../components/trade/AlertsTab'
import BacktestTab from '../components/trade/BacktestTab'
import OptionsTab from '../components/trade/OptionsTab'
import PairsTab from '../components/trade/PairsTab'
import RiskTab from '../components/trade/RiskTab'
import ScannerTab from '../components/trade/ScannerTab'
import ChartTab from '../components/trade/ChartTab'
import JournalTab, { emptyDraft, type JournalDraft } from '../components/trade/JournalTab'
import SizerTab, { type TradePlan } from '../components/trade/SizerTab'
import { Alert, Button, PageHeader, Segmented, Select } from '../components/ui'
import { MARKETS } from '../lib/options'
import { resolveSymbol } from '../lib/symbolMarket'

const TABS = [
  { value: 'chart', label: 'Chart' },
  { value: 'scanner', label: 'Scanner' },
  { value: 'alerts', label: 'Alerts' },
  { value: 'options', label: 'Options' },
  { value: 'backtest', label: 'Backtest' },
  { value: 'pairs', label: 'Pairs' },
  { value: 'size', label: 'Position size' },
  { value: 'journal', label: 'Journal' },
  { value: 'risk', label: 'Risk' },
]

/** Trader workspace: intraday chart with levels, price alerts, risk-based
 * position sizing and a trade journal. Read-only - no order placement. */
export default function TradePage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'chart'
  const symbol = (params.get('symbol') ?? 'RELIANCE').toUpperCase()
  const market = params.get('market') ?? 'india'

  const [text, setText] = useState(symbol)
  const [pickMarket, setPickMarket] = useState(market)
  const [alerts, setAlerts] = useState<PriceAlert[] | null>(null)
  const [plan, setPlan] = useState<TradePlan | null>(null)
  const [draft, setDraft] = useState<JournalDraft>(() => emptyDraft(symbol, market))
  const [risk, setRisk] = useState<RiskStatus | null>(null)

  // The stop-for-the-day banner shows on every tab.
  useEffect(() => {
    const load = () => getRisk().then(setRisk, () => setRisk(null))
    load()
    const id = window.setInterval(load, 60_000)
    return () => window.clearInterval(id)
  }, [])

  const loadAlerts = useCallback(() => {
    listAlerts()
      .then(setAlerts)
      .catch(() => setAlerts([]))
  }, [])
  useEffect(loadAlerts, [loadAlerts])

  useEffect(() => {
    setText(symbol)
    setPickMarket(market)
    setPlan(null)
    setDraft((d) => (d.quantity ? d : emptyDraft(symbol, market)))
  }, [symbol, market])

  function go(next: Partial<{ tab: string; symbol: string; market: string }>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) if (v) p.set(k, v)
    setParams(p, { replace: !next.symbol })
  }

  function open(sym: string, mkt: string) {
    const s = sym.trim().toUpperCase()
    if (s) go({ symbol: s, market: mkt })
  }

  /** Enter / Open on typed text: the market follows the symbol (RELIANCE -> India). */
  async function openTyped() {
    if (!text.trim()) return
    const hit = await resolveSymbol(text, pickMarket, (q) => searchListings(q, 'all', 'all', 10))
    setPickMarket(hit.market)
    open(hit.symbol, hit.market)
  }

  return (
    <div>
      <PageHeader
        title="Trade"
        description="Charts, scanner, alerts, options, backtests, position sizing, journal and daily risk. Read-only: MarketMyna never places orders."
      />

      <div className="mb-5 flex flex-wrap items-end gap-3">
        <div className="min-w-0 basis-full sm:max-w-sm sm:flex-1 sm:basis-auto">
          <SymbolSearch
            value={text}
            onChange={setText}
            detect={{ current: pickMarket, onDetect: setPickMarket }}
            onSelect={(row) => open(row.symbol, row.market)}
            onSubmit={() => void openTyped()}
            placeholder="Symbol, e.g. RELIANCE, AAPL, BTC-USD"
          />
        </div>
        <Select className="min-w-0 flex-1 sm:w-36 sm:flex-none" options={MARKETS} value={pickMarket} onChange={(e) => setPickMarket(e.target.value)} />
        <Button variant="secondary" onClick={() => void openTyped()}>
          Open
        </Button>
      </div>
      <div className="mb-5 max-w-full overflow-x-auto pb-1">
        <Segmented options={TABS} value={tab} onChange={(t) => go({ tab: t })} size="sm" />
      </div>

      {risk?.status === 'stop' && tab !== 'risk' && (
        <div className="mb-5">
          <Alert tone="warn" title="Daily loss limit hit: stop trading for today">
            {risk.reasons[0]}{' '}
            <button type="button" className="underline" onClick={() => go({ tab: 'risk' })}>
              Open Risk
            </button>
          </Alert>
        </div>
      )}

      {tab === 'chart' && (
        <ChartTab
          symbol={symbol}
          market={market}
          alerts={(alerts ?? []).filter((a) => a.symbol === symbol && a.market === market)}
          onAlertsChanged={loadAlerts}
          onSize={(p) => {
            setPlan(p)
            go({ tab: 'size' })
          }}
        />
      )}
      {tab === 'scanner' && <ScannerTab market={market} onOpen={(s, m) => go({ symbol: s, market: m, tab: 'chart' })} />}
      {tab === 'options' && <OptionsTab symbol={symbol} market={market} />}
      {tab === 'backtest' && <BacktestTab symbol={symbol} market={market} />}
      {tab === 'pairs' && <PairsTab symbol={symbol} market={market} />}
      {tab === 'risk' && <RiskTab onStatus={setRisk} />}
      {tab === 'alerts' && <AlertsTab symbol={symbol} market={market} alerts={alerts} onChanged={loadAlerts} />}
      {tab === 'size' && (
        <SizerTab
          symbol={symbol}
          market={market}
          plan={plan}
          onLog={(t) => {
            setDraft({
              ...emptyDraft(symbol, market),
              side: t.side,
              quantity: String(t.quantity),
              entry_price: String(t.entry),
              stop: String(t.stop),
              target: t.target != null ? String(t.target) : '',
              product: t.product ?? '',
            })
            go({ tab: 'journal' })
          }}
        />
      )}
      {tab === 'journal' && <JournalTab draft={draft} setDraft={setDraft} />}
    </div>
  )
}
