import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { analyzeStream, getAiStatus, type AgentOpinion, type Dashboard, type StreamEvent } from '../api/agent'
import { getQuote, type Quote } from '../api/stocks'
import TradingActivity from '../components/TradingActivity'
import PriceChart from '../components/PriceChart'
import FinancialStatements from '../components/FinancialStatements'
import ShariahCard from '../components/ShariahCard'
import SocialSentimentCard from '../components/SocialSentimentCard'
import PeersCard from '../components/PeersCard'
import ChecklistsCard from '../components/ChecklistsCard'
import DcfCard from '../components/DcfCard'
import EarningsCard from '../components/EarningsCard'
import ThesisCard from '../components/ThesisCard'
import EstimatesCard from '../components/EstimatesCard'
import EtfCard from '../components/EtfCard'
import FundsHoldingCard from '../components/FundsHoldingCard'
import ValuationMeter from '../components/ValuationMeter'
import TradeSetupCard from '../components/TradeSetupCard'
import DividendsCard from '../components/DividendsCard'
import SectionIndex from '../components/SectionIndex'
import StockOverview, { loadOverview } from '../components/StockOverview'
import SectorStrip from '../components/SectorStrip'
import { AreaLayout, NavGroup, NavItem } from '../components/AreaNav'
import { FundDetails, findFund } from '../components/FundDetails'
import SymbolSearch from '../components/SymbolSearch'
import WatchButton from '../components/WatchButton'
import { searchListings, type Listing } from '../api/listings'
import { toast } from '../lib/toast'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Field,
  Icon,
  InfoButton,
  InfoPanel,
  PageHeader,
  Segmented,
  Select,
  SignalBadge,
  Skeleton,
  Spinner,
  Stat,
  useCardHelp,
  type IconName,
} from '../components/ui'
import { cx } from '../lib/cx'
import { compact, errorMessage, num, pct, relativeTime, signed, trendClass } from '../lib/format'
import { MARKETS, MODES, labelFor } from '../lib/options'
import { resolveSymbol } from '../lib/symbolMarket'
import { shows, useSection, type Section } from '../lib/section'

/** What Analyze is for in each login area (null = no area chosen yet). */
const AREA_COPY: Record<Section | 'none', { description: string; mode: string; emptyTitle: string; empty: string }> = {
  trader: {
    description: 'Trend, momentum, support and resistance, volatility and news for short-term trades - plus an AI summary with a bullish / neutral / bearish outlook.',
    mode: 'standard',
    emptyTitle: 'Pick a symbol to check the setup',
    empty: 'Open loads the chart and trading range instantly. Run AI adds an AI summary built on the chart, risk and news.',
  },
  investor: {
    description: 'Business quality, valuation against peers, analyst estimates, dividends and financials for long-term holding - plus an AI view on the business.',
    mode: 'full',
    emptyTitle: 'Pick a business to research',
    empty: 'Open loads the price, valuation and financials instantly. Run AI adds an AI view on the business, its valuation and long-term risks.',
  },
  none: {
    description: 'Live quote, chart, technicals, fundamentals, risk, analyst views and news for any stock - plus an optional multi-agent AI read.',
    mode: 'standard',
    emptyTitle: 'Pick a symbol to start',
    empty: 'Open loads the price and chart instantly. Run AI also runs the AI agent pipeline and streams each stage as it finishes.',
  },
}

type StageStatus = 'pending' | 'running' | 'done' | 'skipped'

interface Stage {
  agent: string
  status: StageStatus
  opinion?: AgentOpinion
  message?: string
}

const RECENT_KEY = 'marketmyna.recent'

/** Mirrors MODE_CHAINS in src/agent/orchestrator.py (specialist's strategy
 * agents are picked at run time and appear as they start). */
function plannedStages(mode: string): string[] {
  if (mode === 'quick') return ['technical', 'decision']
  if (mode === 'standard') return ['technical', 'risk', 'news', 'decision']
  return ['technical', 'risk', 'news', 'sentiment', 'fundamentals', 'decision']
}

type Recent = { symbol: string; market: string; name?: string }

function loadRecent(): Recent[] {
  try {
    // A name typed before names were matched (e.g. a fund saved as a US
    // "symbol") can't load; no real symbol has spaces.
    return (JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]') as Recent[]).filter((r) => !/\s/.test(r.symbol))
  } catch {
    return []
  }
}

function saveRecent(symbol: string, market: string, name?: string) {
  const previous = loadRecent()
  const known = name ?? previous.find((r) => r.symbol === symbol && r.market === market)?.name
  const next = [{ symbol, market, ...(known ? { name: known } : {}) }, ...previous.filter((r) => !(r.symbol === symbol && r.market === market))].slice(0, 12)
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    // storage unavailable (private mode) - recent list is a convenience only
  }
  return next
}

/** Mutual funds (AMFI scheme codes) live in India. */
function isFund(sym: string, mkt: string): boolean {
  return mkt === 'india' && /^\d+$/.test(sym)
}

/** "Parag Parikh Flexi Cap Fund - Direct Plan - Growth" -> "Parag Parikh Flexi Cap Fund". */
function shortFundName(name: string): string {
  return name.split(/\s+-\s+/)[0]
}

type Kind = 'stocks' | 'funds'
const KINDS = [
  { value: 'stocks', label: 'Stocks, ETFs & crypto' },
  { value: 'funds', label: 'Mutual funds' },
]

function prettyAgent(name: string): string {
  return name.replace(/^skill[:_]/, '').replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function AnalyzePage() {
  const [params, setParams] = useSearchParams()
  const [symbol, setSymbol] = useState(params.get('symbol') ?? '')
  const [market, setMarket] = useState(params.get('market') ?? 'us')
  // Two tools on one page: stocks (quote, chart, AI pipeline) and mutual funds
  // (holdings, competitors, SIP). ?view=funds, or a fund's scheme code, opens funds.
  const [kind, setKind] = useState<Kind>(() =>
    params.get('view') === 'funds' || isFund(params.get('symbol') ?? '', params.get('market') ?? '') ? 'funds' : 'stocks',
  )
  // Trader: price action, levels, risk, sentiment. Investor: the business, valuation and income.
  const section = useSection()
  const areaCopy = AREA_COPY[section ?? 'none']
  const [mode, setMode] = useState(areaCopy.mode)
  const [recent, setRecent] = useState(loadRecent)
  const trader = shows(section, 'trader')
  const investor = shows(section, 'investor')

  // The "active" instrument - what quote/chart/results describe. Only
  // changes on submit, so typing in the box doesn't refetch anything.
  // Deep link: /?symbol=AAPL&market=us opens straight onto that quote.
  const [active, setActive] = useState<{ symbol: string; market: string } | null>(() => {
    const s = params.get('symbol')
    return s ? { symbol: s.toUpperCase(), market: params.get('market') ?? 'us' } : null
  })
  const [quote, setQuote] = useState<Quote | null>(null)
  const [quoteError, setQuoteError] = useState<string | null>(null)

  const [stages, setStages] = useState<Stage[]>([])
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  // Run AI needs a model (a key in Settings, or LLM_MODEL for a local one); null while checking.
  // Re-checked when the tab comes back into view, e.g. after adding a key in Settings.
  const [aiReady, setAiReady] = useState<boolean | null>(null)
  useEffect(() => {
    let cancelled = false
    const load = () =>
      getAiStatus()
        .then((s) => !cancelled && setAiReady(s.configured))
        .catch(() => !cancelled && setAiReady(null))
    load()
    const onVisible = () => document.visibilityState === 'visible' && load()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])
  const noAi = aiReady === false
  const abortRef = useRef<AbortController | null>(null)
  // NSE <-> BSE switch: keep the old quote on screen until the new one lands,
  // so the card never collapses to skeletons and back.
  const keepQuoteRef = useRef(false)
  const fundRef = useRef<HTMLDivElement>(null)

  // Mutual funds (AMFI scheme codes, India) get the fund analysis, not a stock quote.
  const fundMode = active != null && isFund(active.symbol, active.market)
  const recentOfKind = recent.filter((r) => isFund(r.symbol, r.market) === (kind === 'funds'))
  const [fund, setFund] = useState<Listing | null>(null)
  const [fundError, setFundError] = useState<string | null>(null)
  useEffect(() => {
    if (!active || !isFund(active.symbol, active.market)) return setFund(null)
    let cancelled = false
    setFund(null)
    setFundError(null)
    findFund(active.symbol)
      .then((f) => !cancelled && (f ? setFund(f) : setFundError(`No mutual fund with scheme code ${active.symbol}.`)))
      .catch((err) => !cancelled && setFundError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [active])

  useEffect(() => {
    if (!active || isFund(active.symbol, active.market)) return
    let cancelled = false
    if (!keepQuoteRef.current) setQuote(null)
    keepQuoteRef.current = false
    setQuoteError(null)
    getQuote(active.symbol, active.market)
      .then((q) => !cancelled && setQuote(q))
      .catch((err) => {
        if (cancelled) return
        setQuote(null)
        setQuoteError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [active])

  useEffect(() => () => abortRef.current?.abort(), [])

  /** remember=false: switching NSE/BSE of the same share stays out of Recent,
   * so the chips row above doesn't grow and push the page around. */
  function switchKind(next: Kind) {
    if (next === kind) return
    abortRef.current?.abort()
    setKind(next)
    setSymbol('')
    setActive(null)
    setDashboard(null)
    setStages([])
    setError(null)
    setParams(next === 'funds' ? { view: 'funds' } : {}, { replace: true })
  }

  function select(sym: string, mkt: string, remember = true, name?: string) {
    const clean = sym.trim().toUpperCase()
    if (!clean) return null
    const fund = isFund(clean, mkt)
    if (fund !== (kind === 'funds')) setKind(fund ? 'funds' : 'stocks')
    // Switching instrument: drop the previous symbol's AI results (and any
    // in-flight run) so they never render next to the new quote.
    if (clean !== active?.symbol || mkt !== active?.market) {
      abortRef.current?.abort()
      setDashboard(null)
      setStages([])
      setError(null)
    }
    setSymbol(clean)
    setMarket(mkt)
    setActive({ symbol: clean, market: mkt })
    setParams(fund ? { view: 'funds', symbol: clean, market: mkt } : { symbol: clean, market: mkt }, { replace: true })
    if (remember) setRecent(saveRecent(clean, mkt, name))
    return clean
  }

  /** Typed text -> its symbol and market (RELIANCE -> India, BTC-USD -> Crypto), then load it. */
  async function selectTyped(): Promise<{ symbol: string; market: string } | null> {
    const hit = await resolveSymbol(symbol, market, (q) => searchListings(q, 'all', 'all', 10))
    const clean = select(hit.symbol, hit.market)
    return clean ? { symbol: clean, market: hit.market } : null
  }

  function onEvent(event: StreamEvent) {
    switch (event.event) {
      case 'stage_start':
        setStages((prev) => {
          if (prev.some((s) => s.agent === event.agent)) {
            return prev.map((s) => (s.agent === event.agent ? { ...s, status: 'running' } : s))
          }
          // Unplanned stage (a specialist skill agent) - slot it in before decision.
          const i = prev.findIndex((s) => s.agent === 'decision')
          const stage: Stage = { agent: event.agent, status: 'running' }
          return i === -1 ? [...prev, stage] : [...prev.slice(0, i), stage, ...prev.slice(i)]
        })
        break
      case 'stage_done':
        setStages((prev) => prev.map((s) => (s.agent === event.agent ? { ...s, status: 'done', opinion: event.opinion } : s)))
        break
      case 'stage_skipped':
        setStages((prev) => prev.map((s) => (s.agent === event.agent ? { ...s, status: 'skipped', message: event.message } : s)))
        break
      case 'done':
        setDashboard(event.dashboard)
        break
      case 'error':
        setError(readableError(event.message))
        break
    }
  }

  /** Runs the AI on `target` (the open stock), or on what's typed in the box. */
  async function runAnalysis(target?: { symbol: string; market: string }) {
    if (running) return
    const picked = target ?? (await selectTyped())
    if (!picked) return
    const { symbol: clean, market } = picked
    openView('ai', picked)
    const controller = new AbortController()
    abortRef.current = controller
    setRunning(true)
    setError(null)
    setDashboard(null)
    setStages(plannedStages(mode).map((agent) => ({ agent, status: 'pending' })))
    try {
      await analyzeStream({ symbol: clean, market, mode, area: section }, onEvent, controller.signal)
    } catch (err) {
      if (controller.signal.aborted) {
        toast.info('Analysis cancelled')
      } else {
        setError(readableError(errorMessage(err)))
      }
    } finally {
      setRunning(false)
      // The run is over (finished, failed or cancelled): nothing is still running.
      setStages((prev) => prev.map((s) => (s.status === 'running' || s.status === 'pending' ? { ...s, status: 'skipped' } : s)))
      abortRef.current = null
    }
  }

  // The open stock is one area: a menu switches between its summary, the AI
  // analysis and each group of data cards, so only a few cards show at a time.
  const crypto = active?.market === 'crypto'
  const views = VIEWS.filter((v) => (!v.investor || investor) && !(v.noCrypto && crypto))
  const requested = params.get('tab') ?? 'summary'
  const view: ViewId = views.some((v) => v.id === requested) ? (requested as ViewId) : 'summary'
  // Views opened so far stay mounted (hidden) so switching back is instant.
  const [visited, setVisited] = useState<ViewId[]>([])
  const stockKey = active ? `${active.symbol}:${active.market}` : ''
  useEffect(() => setVisited([]), [stockKey])
  useEffect(() => {
    if (!visited.includes(view)) setVisited((v) => [...v, view])
  }, [view, visited])
  // Warm the shared overview so Technical, Business and Analysts open at once.
  useEffect(() => {
    if (active && !isFund(active.symbol, active.market)) loadOverview(active.symbol, active.market).catch(() => {})
  }, [active])
  const areaRef = useRef<HTMLDivElement>(null)

  function openView(next: ViewId, on: { symbol: string; market: string } | null = active) {
    if (!on) return
    setParams(next === 'summary' ? { symbol: on.symbol, market: on.market } : { symbol: on.symbol, market: on.market, tab: next }, { replace: true })
    // Opened from far down the page: bring the new view's top into sight.
    const top = areaRef.current?.getBoundingClientRect().top
    if (top != null && top < 0) areaRef.current?.scrollIntoView({ block: 'start' })
  }

  function renderView(id: ViewId, on: { symbol: string; market: string }) {
    const { symbol: sym, market: mkt } = on
    switch (id) {
      case 'summary':
        return (
          <>
            <QuoteCard
              symbol={sym}
              market={mkt}
              quote={quote}
              error={quoteError}
              onExchange={(next) => {
                keepQuoteRef.current = true
                select(next, mkt, false)
              }}
            />
            {section === 'trader' && <TradeSetupCard symbol={sym} market={mkt} />}
            <AiTeaser dashboard={dashboard} running={running} noAi={noAi} onOpen={() => openView('ai')} onRun={() => void runAnalysis(on)} />
          </>
        )
      case 'ai':
        return (
          <>
            <AiRunCard
              noAi={noAi}
              mode={mode}
              onMode={setMode}
              stages={stages}
              running={running}
              onRun={() => void runAnalysis(on)}
              onCancel={() => abortRef.current?.abort()}
            />
            {error && (
              <Alert title="Analysis failed" onDismiss={() => setError(null)}>
                {error}
              </Alert>
            )}
            {dashboard && <DecisionCard dashboard={dashboard} />}
            {dashboard && <OpinionsCard opinions={dashboard.opinions} />}
          </>
        )
      case 'technical':
        return <StockOverview symbol={sym} market={mkt} investor={investor} parts={['technical', 'risk']} />
      case 'news':
        return (
          <>
            <StockOverview symbol={sym} market={mkt} parts={['news']} />
            {/* Traders read the mood; investors read it for red flags (governance, dilution, lawsuits). */}
            {(trader || investor) && <SocialSentimentCard symbol={sym} market={mkt} />}
          </>
        )
      case 'business':
        return <StockOverview symbol={sym} market={mkt} parts={['fundamentals', 'profile', 'leadership', 'ownership', 'mdna']} />
      case 'financials':
        return <FinancialStatements symbol={sym} market={mkt} />
      case 'value':
        return (
          <>
            <ValuationMeter symbol={sym} market={mkt} />
            <DcfCard symbol={sym} market={mkt} />
            <PeersCard symbol={sym} market={mkt} />
            <EstimatesCard symbol={sym} market={mkt} />
          </>
        )
      case 'holdings':
        return (
          <>
            <EtfCard symbol={sym} market={mkt} />
            <DividendsCard symbol={sym} market={mkt} />
            <FundsHoldingCard symbol={sym} market={mkt} />
          </>
        )
      case 'events':
        return (
          <>
            <StockOverview symbol={sym} market={mkt} investor={investor} parts={['analysts']} />
            <EarningsCard symbol={sym} market={mkt} />
          </>
        )
      case 'checks':
        return (
          <>
            {investor && <ChecklistsCard symbol={sym} market={mkt} />}
            <ShariahCard symbol={sym} market={mkt} />
          </>
        )
      case 'thesis':
        return <ThesisCard symbol={sym} market={mkt} />
    }
  }

  function nav(rail: boolean) {
    const item = (v: (typeof views)[number]) => (
      <NavItem
        key={v.id}
        rail={rail}
        selected={v.id === view}
        icon={v.icon}
        label={v.id === 'checks' && !investor ? 'Ethical screen' : v.label}
        onClick={() => openView(v.id)}
        extra={
          v.id !== 'ai' ? undefined : running ? (
            <Spinner className="h-3.5 w-3.5 text-accent-fg" />
          ) : dashboard ? (
            <Icon name="check" className="h-3.5 w-3.5 text-up" />
          ) : undefined
        }
      />
    )
    return (
      <>
        {views.filter((v) => !v.group).map(item)}
        {VIEW_GROUPS.map((g) => {
          const items = views.filter((v) => v.group === g.id)
          return items.length ? (
            <NavGroup key={g.id} rail={rail} label={g.label}>
              {items.map(item)}
            </NavGroup>
          ) : null
        })}
      </>
    )
  }

  return (
    <div>
      <PageHeader
        title="Analyze"
        description={
          kind === 'funds'
            ? 'Any Indian mutual fund: returns and NAV history, every stock it holds, sectors and company sizes, how it ranks against its competitors, and SIP planning.'
            : areaCopy.description
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-3">
          <Segmented size="sm" options={KINDS} value={kind} onChange={(v) => switchKind(v as Kind)} />
          {recentOfKind.length > 0 && (
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <span className="me-1 text-xs text-faint">Recent</span>
              {recentOfKind.slice(0, 8).map((r) =>
                kind === 'funds' ? (
                  <button
                    key={`${r.symbol}:${r.market}`}
                    type="button"
                    onClick={() => select(r.symbol, r.market)}
                    title={r.name ?? `Scheme ${r.symbol}`}
                    className="max-w-[16rem] truncate rounded-md bg-raised px-2 py-0.5 text-xs text-muted hover:text-fg"
                  >
                    {r.name ? shortFundName(r.name) : `Scheme ${r.symbol}`}
                  </button>
                ) : (
                  <button
                    key={`${r.symbol}:${r.market}`}
                    type="button"
                    onClick={() => select(r.symbol, r.market)}
                    title={r.name}
                    className={cx(
                      'rounded-md px-2 py-0.5 font-mono text-xs hover:text-fg',
                      active?.symbol === r.symbol && active.market === r.market ? 'bg-accent-soft text-fg' : 'bg-raised text-muted',
                    )}
                  >
                    {r.symbol}
                    {r.market !== 'us' && <span className="ms-1 text-faint">{labelFor(MARKETS, r.market)}</span>}
                  </button>
                ),
              )}
            </div>
          )}
        </div>
        {kind === 'funds' ? (
          <form
            className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_auto]"
            onSubmit={(e) => {
              e.preventDefault()
              if (/^\d+$/.test(symbol.trim())) select(symbol, 'india')
            }}
          >
            <Field label="Mutual fund">
              <SymbolSearch
                value={symbol}
                onChange={setSymbol}
                market="india"
                type="mf"
                onSelect={(row) => select(row.symbol, 'india', true, row.name)}
                onSubmit={() => /^\d+$/.test(symbol.trim()) && select(symbol, 'india')}
                placeholder="Search by fund name, fund house or scheme code (e.g. Parag Parikh Flexi Cap, HDFC Mid Cap)"
                autoFocus
              />
            </Field>
            <div className="flex items-end">
              <Button type="submit" icon="search" disabled={!/^\d+$/.test(symbol.trim())} title="Or pick a fund from the list as you type">
                Open fund
              </Button>
            </div>
          </form>
        ) : (
        <form
          className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_180px_auto]"
          onSubmit={(e) => {
            e.preventDefault()
            void selectTyped()
          }}
        >
          <Field label="Symbol">
            <SymbolSearch
              value={symbol}
              onChange={setSymbol}
              onSelect={(row) => select(row.symbol, row.market, true, row.name)}
              onSubmit={() => symbol.trim() && void selectTyped()}
              detect={{ current: market, onDetect: setMarket }}
              exclude={['mf']}
              placeholder="Search any stock, ETF or crypto (e.g. Reliance, AAPL, BTC)"
              autoFocus
            />
          </Field>
          <Field label="Market">
            <Select options={MARKETS} value={market} onChange={(e) => setMarket(e.target.value)} />
          </Field>
          <div className="flex items-end gap-2">
            <Button type="submit" icon="search" disabled={!symbol.trim()} title="Load the price, chart and every data card - no AI">
              Open
            </Button>
            {running ? (
              <Button variant="danger" icon="stop" onClick={() => abortRef.current?.abort()}>
                Cancel AI
              </Button>
            ) : (
              <Button
                variant="secondary"
                icon="play"
                disabled={noAi || !symbol.trim() || isFund(symbol.trim(), market)}
                onClick={() => void runAnalysis()}
                title={
                  noAi
                    ? NO_AI_HINT
                    : isFund(symbol.trim(), market)
                      ? 'Mutual funds get their full analysis and an AI fund review below'
                      : `Run the AI on this stock (${labelFor(MODES, mode)} depth - change it under AI analysis)`
                }
              >
                Run AI
              </Button>
            )}
          </div>
        </form>
        )}
      </Card>

      {!active ? (
        <Card className="mt-6">
          {kind === 'funds' ? (
            <EmptyState
              icon="portfolio"
              title="Pick a mutual fund"
              description="Search by name, fund house or scheme code. You'll see its returns, NAV chart, every stock it holds with sectors and company sizes, what it bought and sold last month, where it ranks among its competitors, and a SIP planner."
            />
          ) : (
            <EmptyState icon="analyze" title={areaCopy.emptyTitle} description={areaCopy.empty} />
          )}
        </Card>
      ) : fundMode ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div ref={fundRef} className="min-w-0">
            <Card>
              {fundError ? (
                <CardBody>
                  <Alert title="Fund not found">{fundError}</Alert>
                </CardBody>
              ) : !fund ? (
                <CardBody>
                  <Skeleton className="h-64 w-full" />
                </CardBody>
              ) : (
                <>
                  <CardHeader
                    title={fund.name}
                    description={[fund.amc, fund.sector, fund.plan && `${fund.plan} plan`, fund.option].filter(Boolean).join(' · ')}
                    actions={
                      <div className="flex flex-wrap gap-2">
                        <WatchButton showLabel item={{ symbol: fund.symbol, market: fund.market, type: 'mf', name: fund.name }} />
                        <Link
                          to={`/portfolio?add=${encodeURIComponent(fund.symbol)}&market=mf`}
                          className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line px-2 py-1 text-xs text-muted hover:border-line-strong hover:text-fg"
                        >
                          <Icon name="portfolio" className="h-3.5 w-3.5" />
                          Add to portfolio
                        </Link>
                      </div>
                    }
                  />
                  <CardBody>
                    <FundDetails fund={fund} onOpenFund={(code) => select(code, 'india')} />
                  </CardBody>
                </>
              )}
            </Card>
          </div>
          <aside className="h-fit space-y-4 lg:sticky lg:top-8 lg:max-h-[calc(100vh-4rem)] lg:overflow-y-auto">
            <SectionIndex root={fundRef} />
          </aside>
        </div>
      ) : (
        <div ref={areaRef} className="mt-6 scroll-mt-4">
          <AreaLayout label="Stock views" nav={nav}>
            {view !== 'summary' && <StockStrip symbol={active.symbol} market={active.market} quote={quote} />}
            {VIEWS.filter((v) => visited.includes(v.id) || v.id === view).map((v) => (
              <div key={v.id} hidden={v.id !== view} className="space-y-6">
                {renderView(v.id, active)}
              </div>
            ))}
          </AreaLayout>
        </div>
      )}
    </div>
  )
}

/** The open stock's views, in menu order. `investor`: business views, off in
 * the Trader section; `noCrypto`: coins have no business to read. */
type ViewId = 'summary' | 'ai' | 'technical' | 'news' | 'business' | 'financials' | 'value' | 'holdings' | 'events' | 'checks' | 'thesis'
type ViewGroup = 'price' | 'business' | 'checks'
const VIEW_GROUPS: { id: ViewGroup; label: string }[] = [
  { id: 'price', label: 'Price & mood' },
  { id: 'business', label: 'The business' },
  { id: 'checks', label: 'Checks & notes' },
]
const VIEWS: { id: ViewId; label: string; icon: IconName; group?: ViewGroup; investor?: boolean; noCrypto?: boolean }[] = [
  { id: 'summary', label: 'Summary', icon: 'home' },
  { id: 'ai', label: 'AI analysis', icon: 'cpu' },
  { id: 'technical', label: 'Technical & risk', icon: 'candles', group: 'price' },
  { id: 'news', label: 'News & mood', icon: 'globe', group: 'price' },
  { id: 'business', label: 'Business', icon: 'grid', group: 'business', investor: true, noCrypto: true },
  { id: 'financials', label: 'Financials', icon: 'sort', group: 'business', investor: true, noCrypto: true },
  { id: 'value', label: 'Valuation', icon: 'compare', group: 'business', investor: true, noCrypto: true },
  { id: 'holdings', label: 'Holdings & dividends', icon: 'portfolio', group: 'business', investor: true, noCrypto: true },
  { id: 'events', label: 'Analysts & earnings', icon: 'clock', group: 'checks', noCrypto: true },
  { id: 'checks', label: 'Checklists & ethical', icon: 'check', group: 'checks' },
  { id: 'thesis', label: 'My thesis', icon: 'pencil', group: 'checks' },
]

/** Which stock the view is about, with its price, above every view but the summary. */
function StockStrip({ symbol, market, quote }: { symbol: string; market: string; quote: Quote | null }) {
  return (
    <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="font-mono text-base font-semibold">{symbol}</span>
      <span className="rounded bg-raised px-1.5 py-0.5 text-xs text-muted">{labelFor(MARKETS, market)}</span>
      {quote && (
        <>
          <span className="tabular font-semibold">{num(quote.price)}</span>
          <span className={cx('tabular text-sm font-medium', trendClass(quote.change))}>
            {signed(quote.change)} ({pct(quote.change_percent)})
          </span>
        </>
      )}
    </div>
  )
}

/** The AI's place on the summary: run it, watch it run, or its summary in short. */
/** Shown where Run AI is off: why, and where to fix it. */
const NO_AI_HINT = 'Add an AI key in Settings first - the data cards work without one.'

function NoAiNote() {
  return (
    <p className="mt-1 text-xs text-warn">
      No AI model is set up, so Run AI is off.{' '}
      <Link to="/settings" className="font-medium text-accent hover:underline">
        Add an AI key in Settings
      </Link>{' '}
      (or set LLM_MODEL for a local model). The data cards in the menu work without one.
    </p>
  )
}

function AiTeaser({
  dashboard,
  running,
  noAi,
  onOpen,
  onRun,
}: {
  dashboard: Dashboard | null
  running: boolean
  noAi: boolean
  onOpen: () => void
  onRun: () => void
}) {
  return (
    <Card>
      <CardBody className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Icon name="cpu" className="h-4 w-4 text-accent" />
            AI read
            {running && <Spinner className="h-3.5 w-3.5 text-accent-fg" />}
          </div>
          <p className={cx('mt-1 text-sm text-muted', dashboard && 'line-clamp-2')}>
            {running
              ? 'The agents are working - each stage shows as it finishes.'
              : dashboard?.analysis_summary ?? 'The data cards in the menu need no AI. Run it for a call built on the chart, risk and news.'}
          </p>
          {noAi && !running && !dashboard && <NoAiNote />}
        </div>
        {running || dashboard ? (
          <Button variant="secondary" size="sm" onClick={onOpen}>
            {running ? 'Watch it run' : 'Full analysis'}
          </Button>
        ) : (
          <Button size="sm" icon="play" onClick={onRun} disabled={noAi} title={noAi ? NO_AI_HINT : undefined}>
            Run AI
          </Button>
        )}
      </CardBody>
    </Card>
  )
}

/** Pipeline errors in words a user can act on. */
function readableError(message: string): string {
  if (/no llm_model configured/i.test(message)) {
    return 'No AI model is set up on this server yet, so the AI step could not run. The market data on this page works without it; add an AI key under Settings → AI keys.'
  }
  if (/not enough (price )?history/i.test(message)) {
    return 'Not enough price history for this listing to analyse it. Try the other exchange or a longer-listed stock.'
  }
  return message
}

/** Indian shares trade on both NSE and BSE: RELIANCE (or RELIANCE.NS) is
 * the NSE listing, RELIANCE.BO the BSE one. */
function indianListing(symbol: string): { base: string; exchange: 'NSE' | 'BSE' } {
  const s = symbol.toUpperCase()
  if (s.endsWith('.BO')) return { base: s.slice(0, -3), exchange: 'BSE' }
  return { base: s.endsWith('.NS') ? s.slice(0, -3) : s, exchange: 'NSE' }
}

function QuoteCard({
  symbol,
  market,
  quote,
  error,
  onExchange,
}: {
  symbol: string
  market: string
  quote: Quote | null
  error: string | null
  /** Switch the review to the same share's other exchange listing. */
  onExchange: (symbol: string) => void
}) {
  const india = market === 'india' && !symbol.startsWith('^')
  const lookup = india ? indianListing(symbol).base : symbol
  // Resolve the listing entry (type + full name) so the star matches the
  // same item the Markets page and Watchlist use, e.g. NIFTYBEES is an ETF.
  const [listing, setListing] = useState<Listing | null>(null)
  useEffect(() => {
    let cancelled = false
    setListing(null)
    searchListings(lookup, market === 'global' ? 'all' : market, 'all', 5)
      .then((rows) => {
        if (!cancelled) setListing(rows.find((r) => r.symbol.toUpperCase() === lookup.toUpperCase()) ?? null)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [lookup, market])
  // Shares and ETFs only: mutual funds (numeric AMFI scheme codes) have no exchange price.
  const exchangeTraded = india && listing?.type !== 'mf' && !/^\d+$/.test(lookup)
  const help = useCardHelp('Quote & chart')

  return (
    <Card id="section-quote" section="Quote & chart">
      <CardBody>
        {/* Header and NSE/BSE picker share a row with the picker pinned right, and
            the stats sit on their own row, so switching exchange moves nothing. */}
        <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {/* Indian shares: the base symbol; the NSE / BSE picker shows the listing, and
                  a constant title width keeps the buttons from re-wrapping on a switch. */}
              <h2 className="font-mono text-lg font-semibold">{exchangeTraded ? lookup : symbol}</h2>
              <span className="rounded bg-raised px-1.5 py-0.5 text-xs text-muted">{labelFor(MARKETS, market)}</span>
              <InfoButton topic="Quote & chart" open={help.open} onToggle={help.toggle} panelId={help.panelId} />
              <WatchButton
                showLabel
                item={{
                  symbol: listing?.symbol ?? symbol,
                  market: listing?.market ?? market,
                  type: listing?.type ?? (market === 'crypto' ? 'crypto' : 'stock'),
                  name: listing?.name ?? symbol,
                }}
              />
              <Link
                to={`/trade?symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}`}
                className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line px-2 py-1 text-xs text-muted hover:border-line-strong hover:text-fg"
              >
                <Icon name="candles" className="h-3.5 w-3.5" />
                Open in Trade
              </Link>
              <Link
                to={`/portfolio?add=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}${quote?.price != null ? `&price=${quote.price}` : ''}`}
                className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line px-2 py-1 text-xs text-muted hover:border-line-strong hover:text-fg"
              >
                <Icon name="portfolio" className="h-3.5 w-3.5" />
                Add to portfolio
              </Link>
            </div>
            <InfoPanel topic="Quote & chart" open={help.open} onClose={help.close} id={help.panelId} />
            {listing && listing.name !== symbol && <p className="text-sm text-muted">{listing.name}</p>}
            {quote ? (
              <div className="mt-1 flex items-baseline gap-3">
                <span className="tabular text-3xl font-semibold tracking-tight">{num(quote.price)}</span>
                <span className={cx('tabular text-sm font-medium', trendClass(quote.change))}>
                  {signed(quote.change)} ({pct(quote.change_percent)})
                </span>
              </div>
            ) : error ? (
              <p className="mt-1 text-sm text-down">Quote unavailable: {error}</p>
            ) : (
              <div className="mt-1 flex h-9 items-center">
                <Skeleton className="h-8 w-48" />
              </div>
            )}
          </div>
          {exchangeTraded && <ExchangePicker symbol={symbol} quote={quote} onPick={onExchange} />}
        </div>
        {!error && (
          <div className="mb-5 grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
            <Stat label="Open" value={quote ? num(quote.open) : <Skeleton className="mt-1 h-5 w-20" />} />
            <Stat label="Prev close" value={quote ? num(quote.previous_close) : <Skeleton className="mt-1 h-5 w-20" />} />
            <Stat
              label="Day range"
              value={
                quote ? (
                  // Two numbers: let them wrap rather than cut the high off.
                  <span className="block whitespace-normal leading-snug">
                    {num(quote.day_low)} – {num(quote.day_high)}
                  </span>
                ) : (
                  <Skeleton className="mt-1 h-5 w-28" />
                )
              }
            />
            <Stat
              label="Volume"
              value={quote ? compact(quote.volume) : <Skeleton className="mt-1 h-5 w-16" />}
              sub={quote?.market_cap ? `Cap ${compact(quote.market_cap)}` : '\u00a0'}
            />
          </div>
        )}
        {!error && listing?.type !== 'mf' && <SectorStrip symbol={lookup} market={market} />}
        <PriceChart symbol={symbol} market={market} />
        {(india ? exchangeTraded : listing?.type !== 'mf' && market !== 'global') && (
          <TradingActivity symbol={exchangeTraded ? lookup : symbol} market={market} />
        )}
      </CardBody>
    </Card>
  )
}

/** NSE and BSE prices side by side; picking one reviews that listing. */
function ExchangePicker({ symbol, quote, onPick }: { symbol: string; quote: Quote | null; onPick: (symbol: string) => void }) {
  const { base, exchange } = indianListing(symbol)
  const other = exchange === 'NSE' ? 'BSE' : 'NSE'
  const otherSymbol = other === 'BSE' ? `${base}.BO` : base
  // Both listings' last known quotes, kept across a switch so neither price
  // blanks out (and nothing resizes) while the new one loads.
  const [known, setKnown] = useState<Partial<Record<'NSE' | 'BSE', Quote>>>({})
  const [otherMissing, setOtherMissing] = useState(false)
  useEffect(() => setKnown({}), [base])
  useEffect(() => {
    if (quote) setKnown((k) => ({ ...k, [exchange]: quote }))
  }, [quote, exchange])
  useEffect(() => {
    let cancelled = false
    setOtherMissing(false)
    getQuote(otherSymbol, 'india')
      .then((q) => !cancelled && setKnown((k) => ({ ...k, [other]: q })))
      .catch(() => !cancelled && setOtherMissing(true))
    return () => {
      cancelled = true
    }
  }, [otherSymbol, other])

  const quotes: Record<'NSE' | 'BSE', Quote | null> = {
    NSE: (exchange === 'NSE' ? quote : null) ?? known.NSE ?? null,
    BSE: (exchange === 'BSE' ? quote : null) ?? known.BSE ?? null,
  }
  const gap = quotes[exchange] && quotes[other] ? quotes[exchange]!.price - quotes[other]!.price : null

  return (
    <div className="w-full shrink-0 sm:w-[18rem]">
      <div className="mb-1.5 text-xs text-muted">Exchange</div>
      <div role="radiogroup" aria-label="Exchange" className="grid grid-cols-2 gap-1 rounded-xl bg-raised p-1">
        {(['NSE', 'BSE'] as const).map((ex) => {
          const q = quotes[ex]
          const selected = ex === exchange
          const missing = ex === other && otherMissing
          return (
            <button
              key={ex}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={selected || missing}
              onClick={() => onPick(ex === 'BSE' ? `${base}.BO` : base)}
              className={cx(
                'min-w-0 rounded-lg px-2.5 py-1.5 text-start transition-colors',
                selected ? 'bg-surface shadow-card ring-1 ring-accent/40' : 'hover:bg-surface/60 disabled:opacity-60',
              )}
            >
              <div className="flex items-baseline justify-between gap-1">
                <span className="text-xs font-semibold tracking-wide text-muted">{ex}</span>
                {q && <span className={cx('tabular text-[11px]', trendClass(q.change))}>{pct(q.change_percent)}</span>}
              </div>
              <div className="flex h-6 items-center">
                {q ? (
                  <span className="tabular truncate font-semibold">₹{num(q.price)}</span>
                ) : missing ? (
                  <div className="text-xs text-faint">Not listed</div>
                ) : (
                  <Skeleton className="h-4 w-20" />
                )}
              </div>
            </button>
          )
        })}
      </div>
      {/* Always takes its line, so the gap note appearing doesn't push the chart down. */}
      <p className="mt-1.5 h-4 text-xs text-muted">
        {gap != null && Math.abs(gap) >= 0.01
          ? `${exchange} is ₹${num(Math.abs(gap))} ${gap > 0 ? 'above' : 'below'} ${other}`
          : gap != null
            ? 'Same price on both'
            : ''}
      </p>
    </div>
  )
}

/** The AI analysis view: its depth, run / cancel, and each agent as it reports in. */
function AiRunCard({
  noAi,
  mode,
  onMode,
  stages,
  running,
  onRun,
  onCancel,
}: {
  noAi: boolean
  mode: string
  onMode: (mode: string) => void
  stages: Stage[]
  running: boolean
  onRun: () => void
  onCancel: () => void
}) {
  return (
    <Card help="Agent pipeline">
      <CardHeader
        title="AI analysis"
        description={running ? 'Streaming live…' : stages.length ? 'Last run' : 'AI agents read the chart, risk and news, then give their view'}
        actions={
          running ? (
            <Button variant="danger" size="sm" icon="stop" onClick={onCancel}>
              Cancel
            </Button>
          ) : (
            <Button size="sm" icon="play" onClick={onRun} disabled={noAi} title={noAi ? NO_AI_HINT : undefined}>
              {stages.length ? 'Run again' : 'Run AI'}
            </Button>
          )
        }
      />
      {noAi && !running && (
        <div className="border-b border-line px-5 py-3">
          <NoAiNote />
        </div>
      )}
      <div className="border-b border-line px-5 py-4">
        <span className="mb-1.5 block text-xs font-medium text-muted">
          Depth <span className="font-normal text-faint">· the data cards are the same at every depth</span>
        </span>
        <Segmented options={MODES} value={mode} onChange={onMode} showHint />
      </div>
      {stages.length === 0 ? (
        <p className="px-5 py-4 text-xs text-muted">Run AI to see each agent report in as it completes.</p>
      ) : (
        <ol className="grid gap-x-8 px-5 py-4 md:grid-cols-2">
          {stages.map((s) => (
            <li key={s.agent} className="flex gap-3 py-2">
              <StageIcon status={s.status} />
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex items-center justify-between gap-2">
                  <span className={cx('text-sm font-medium', s.status === 'pending' && 'text-faint')}>
                    {prettyAgent(s.agent)}
                  </span>
                  <StageReading opinion={s.opinion} />
                </div>
                {s.status === 'skipped' && <p className="mt-0.5 text-xs text-warn">{s.message ?? 'Skipped'}</p>}
                {s.opinion?.summary && <p className="mt-0.5 line-clamp-3 text-xs text-muted">{s.opinion.summary}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

/** The tag beside a finished agent: technical = what its indicators read,
 * news = the tone of the headlines, risk = the computed risk level,
 * fundamentals = the filings score band. Facts about the data, never a
 * call; the decision agent's own signal only appears for the owner. */
function StageReading({ opinion }: { opinion?: AgentOpinion }) {
  if (!opinion) return null
  // The crowd's mood online, not a verdict on the stock.
  if (opinion.agent_name === 'sentiment' && opinion.signal) {
    const tone = ['bullish', 'positive'].includes(opinion.signal) ? 'up' : ['bearish', 'negative'].includes(opinion.signal) ? 'down' : 'warn'
    const posts = opinion.details?.posts
    return (
      <span title={typeof posts === 'number' ? `${posts} posts in the last 7 days` : undefined}>
        <Badge tone={tone}>chatter {opinion.signal}</Badge>
      </span>
    )
  }
  if (opinion.signal) return <SignalBadge value={opinion.signal} />
  const d = opinion.details ?? {}
  if (opinion.agent_name === 'risk' && typeof d.risk_level === 'string') {
    return <SignalBadge value={`${d.risk_level}_risk`} />
  }
  const score = (d.financial_statements as { overall?: { score?: number } } | undefined)?.overall?.score
  if (opinion.agent_name === 'fundamentals' && typeof score === 'number') {
    const band = score >= 60 ? 'bullish' : score >= 40 ? 'neutral' : 'bearish'
    return <span title={`Filings score ${score}/100`}><SignalBadge value={band} /></span>
  }
  return null
}

function StageIcon({ status }: { status: StageStatus }) {
  const base = 'relative z-10 grid h-6 w-6 shrink-0 place-items-center rounded-full ring-1'
  if (status === 'running') return <span className={cx(base, 'bg-accent-soft text-accent-fg ring-accent/40')}><Spinner className="h-3.5 w-3.5" /></span>
  if (status === 'done') return <span className={cx(base, 'bg-up-soft text-up ring-up/40')}><Icon name="check" className="h-3.5 w-3.5" /></span>
  if (status === 'skipped') return <span className={cx(base, 'bg-warn-soft text-warn ring-warn/40')}><Icon name="x" className="h-3 w-3" /></span>
  return <span className={cx(base, 'bg-canvas ring-line-strong')} />
}

/** The AI's summary and outlook: no buy / sell call, target, stop or technical verdict (src/core/compliance.py). */
function DecisionCard({ dashboard }: { dashboard: Dashboard }) {
  function copy() {
    const lines = [
      `${dashboard.symbol} (${dashboard.market}) – AI analysis${dashboard.outlook ? ` (${dashboard.outlook} outlook)` : ''}`,
      dashboard.analysis_summary ?? '',
      `Risk: ${dashboard.risk_level ?? '-'}`,
      '',
      ...dashboard.opinions.map((o) => `- ${prettyAgent(o.agent_name)} [${o.signal ?? '-'}]: ${o.summary}`),
    ]
    navigator.clipboard.writeText(lines.join('\n')).then(
      () => toast.success('Report copied to clipboard'),
      () => toast.error('Clipboard not available'),
    )
  }

  return (
    <Card id="section-decision" section="AI analysis">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            AI analysis {dashboard.outlook && <SignalBadge value={dashboard.outlook} />}
          </span>
        }
        description={`${labelFor(MODES, dashboard.mode)} mode · generated ${relativeTime(dashboard.generated_at)}`}
        actions={
          <Button variant="ghost" size="sm" onClick={copy}>
            Copy report
          </Button>
        }
      />
      <CardBody>
        {dashboard.analysis_summary && <p className="text-sm leading-relaxed">{dashboard.analysis_summary}</p>}
        <div className="mt-5 grid grid-cols-2 gap-5 border-t border-line pt-5">
          <div>
            <div className="text-xs font-medium text-muted">Risk level</div>
            <div className="mt-1.5"><SignalBadge value={dashboard.risk_level} /></div>
          </div>
        </div>
      </CardBody>
    </Card>
  )
}

const DETAIL_LABELS: Record<string, string> = {
  rsi: 'RSI',
  macd: 'MACD',
  ma: 'Moving average',
  ema: 'EMA',
  sma: 'SMA',
  atr: 'ATR',
  adx: 'ADX',
  obv: 'OBV',
  vwap: 'VWAP',
  eps: 'EPS',
  pe: 'P/E',
  pb: 'P/B',
  ps: 'P/S',
  roe: 'ROE',
  roce: 'ROCE',
  var: 'VaR',
}

function detailLabel(key: string): string {
  const known = DETAIL_LABELS[key.toLowerCase()]
  if (known) return known
  const text = key.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function detailNumber(n: number): string {
  if (!Number.isFinite(n)) return String(n)
  if (Number.isInteger(n)) return n.toLocaleString()
  return n.toLocaleString(undefined, { maximumFractionDigits: Math.abs(n) >= 100 ? 2 : Math.abs(n) >= 1 ? 2 : 4 })
}

type DetailPrimitive = string | number | boolean | null | undefined

function isPrimitive(v: unknown): v is DetailPrimitive {
  return v == null || ['string', 'number', 'boolean'].includes(typeof v)
}

/** Agent evidence (headlines, indicator values, fundamentals) as readable
 *  lists and rows rather than raw JSON. */
function DetailValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value == null || value === '') return <span className="text-faint">—</span>
  if (typeof value === 'number') return <span className="tabular">{detailNumber(value)}</span>
  if (typeof value === 'boolean') return <>{value ? 'Yes' : 'No'}</>
  if (typeof value === 'string') return <>{value}</>
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-faint">None</span>
    return (
      <ul className="list-disc space-y-1 ps-4">
        {value.map((item, i) => (
          <li key={i}>
            <DetailValue value={item} depth={depth + 1} />
          </li>
        ))}
      </ul>
    )
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, v]) => v != null && v !== '')
    // {"value": 35.4} (one indicator reading), maybe with a signal next to it.
    const own = value as Record<string, unknown>
    if ('value' in own && entries.length <= 2 && entries.every(([, v]) => isPrimitive(v))) {
      const extra = entries.find(([k]) => k !== 'value')
      return (
        <>
          <DetailValue value={own.value} depth={depth + 1} />
          {extra && <span className="text-muted"> · {String(extra[1])}</span>}
        </>
      )
    }
    if (depth > 3) return <span className="font-mono">{JSON.stringify(value)}</span>
    return (
      <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted">{detailLabel(k)}</dt>
            <dd className="min-w-0 break-words">
              <DetailValue value={v} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    )
  }
  return <>{String(value)}</>
}

function OpinionsCard({ opinions }: { opinions: AgentOpinion[] }) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <Card id="section-opinions" section="Agent opinions">
      <CardHeader title="Agent opinions" description={`${opinions.length} agents contributed`} />
      <ul className="divide-y divide-line">
        {opinions.map((op) => {
          const details = Object.entries(op.details ?? {}).filter(([, v]) => v != null && v !== '')
          const isOpen = open === op.agent_name
          return (
            <li key={op.agent_name}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : op.agent_name)}
                className="flex w-full items-start gap-3 px-5 py-4 text-start hover:bg-raised/40"
              >
                <Icon name="chevron" className={cx('mt-0.5 h-4 w-4 text-faint transition-transform', isOpen && 'rotate-90')} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{prettyAgent(op.agent_name)}</span>
                    {op.signal && <SignalBadge value={op.signal} />}
                  </div>
                  <p className={cx('mt-1 text-sm text-muted', !isOpen && 'line-clamp-2')}>{op.summary}</p>
                </div>
              </button>
              {isOpen && details.length > 0 && (
                <dl className="mx-5 mb-4 ms-12 grid gap-x-6 gap-y-3 rounded-lg bg-canvas p-4 text-xs sm:grid-cols-2">
                  {details.map(([k, v]) => (
                    <div key={k} className={cx('min-w-0', typeof v === 'object' && 'sm:col-span-2')}>
                      <dt className="text-faint">{detailLabel(k)}</dt>
                      <dd className="mt-0.5 break-words text-fg/90">
                        <DetailValue value={v} />
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
