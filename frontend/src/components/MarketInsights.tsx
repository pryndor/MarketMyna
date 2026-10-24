import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { cx } from '../lib/cx'
import { InsightActive } from '../lib/insight'
import { shows, useSection, type Section } from '../lib/section'
import BigTradesCard from './BigTradesCard'
import CentralBanks from './CentralBanks'
import CommoditiesCard from './CommoditiesCard'
import CountryMacro from './CountryMacro'
import CrudeSensitivity from './CrudeSensitivity'
import DealsCard from './DealsCard'
import FundRotation from './FundRotation'
import HotStocks from './HotStocks'
import IndiaFlows from './IndiaFlows'
import IndiaRatesCard from './IndiaRatesCard'
import MacroDashboard from './MacroDashboard'
import MarketMood from './MarketMood'
import MarketPulse from './MarketPulse'
import MarketValuation from './MarketValuation'
import RatesCard from './RatesCard'
import ScreensCard from './ScreensCard'
import SectorRotation from './SectorRotation'
import WorldMarkets from './WorldMarkets'
import { Button, Card, Icon, Segmented, type IconName } from './ui'
import type { Option } from '../lib/options'

const TAB_KEY = 'marketmyna.insights.tab'

type TabId =
  | 'hot_trade' | 'hot_invest' | 'pulse' | 'rotation' | 'funds' | 'deals' | 'screens' | 'rates'
  | 'mood' | 'flows' | 'world' | 'valuation' | 'macro' | 'countries' | 'commodities' | 'oil'

// Tab names (and the lower-case form for "Showing …") live in locales/<lang>/markets.json under "insights.tabs".
type Tab = {
  id: TabId
  icon: IconName
  /** Markets the section applies to (undefined = all). */
  markets?: string[]
  except?: string[]
  /** Only in this side of the app (untagged = both). */
  section?: Section
  group: Group
  render: (market: string, onCategory: (category: string) => void) => ReactNode
}

// India keeps its own data-rich cards (mutual funds, NSE deals, RBI / IBJA);
// every other market gets its counterpart: ETFs for funds, Form 4 / block
// trades / Stock Connect / whale positioning for big trades, local rates.
const INDIA = ['india', 'all']

type Group = 'stocks' | 'markets' | 'economy'
const GROUPS: Group[] = ['stocks', 'markets', 'economy']
const TABS: Tab[] = [
  // First in each area: hot stocks matched to how that side of the app invests.
  { id: 'hot_trade', group: 'stocks', section: 'trader', icon: 'radar', except: ['all'],
    render: (m) => <HotStocks market={m} area="trader" /> },
  { id: 'hot_invest', group: 'stocks', section: 'investor', icon: 'star', except: ['all'],
    render: (m) => <HotStocks market={m} area="investor" /> },
  { id: 'pulse', group: 'stocks', icon: 'analyze', except: ['all'],
    render: (m, onCategory) => <MarketPulse market={m} onCategory={onCategory} /> },
  { id: 'rotation', group: 'stocks', section: 'investor', icon: 'refresh', markets: ['india', 'us', 'china_a', 'hong_kong', 'crypto'],
    render: (m) => <SectorRotation market={m} /> },
  { id: 'funds', group: 'stocks', section: 'investor', icon: 'portfolio', markets: [...INDIA, 'us', 'hong_kong', 'china_a'],
    render: (m) => (INDIA.includes(m) ? <FundRotation /> : <FundRotation market={m} />) },
  { id: 'deals', group: 'stocks', section: 'trader', icon: 'portfolio', markets: ['india', 'us', 'china_a', 'hong_kong', 'crypto'],
    render: (m) => (m === 'india' ? <DealsCard /> : <BigTradesCard market={m} />) },
  { id: 'screens', group: 'stocks', section: 'investor', icon: 'filter', markets: ['india', 'us', 'hong_kong', 'china_a', 'crypto'],
    render: (m) => <ScreensCard market={m} /> },
  { id: 'rates', group: 'economy', section: 'investor', icon: 'grid', markets: [...INDIA, 'us', 'hong_kong', 'china_a', 'crypto'],
    render: (m) => (INDIA.includes(m) ? <IndiaRatesCard /> : <RatesCard market={m} />) },
  { id: 'mood', group: 'markets', icon: 'radar', markets: ['india', 'us', 'hong_kong', 'china_a', 'crypto'],
    render: (m) => <MarketMood market={m} /> },
  { id: 'flows', group: 'markets', icon: 'compare', markets: INDIA, render: () => <IndiaFlows /> },
  { id: 'world', group: 'markets', icon: 'globe', render: () => <WorldMarkets /> },
  { id: 'valuation', group: 'markets', section: 'investor', icon: 'sort', markets: [...INDIA, 'us'],
    render: (m) => <MarketValuation market={m} /> },
  { id: 'macro', group: 'economy', section: 'investor', icon: 'globe', render: () => <MacroDashboard /> },
  { id: 'countries', group: 'economy', section: 'investor', icon: 'globe',
    render: () => (
      <>
        <CountryMacro />
        <CentralBanks />
      </>
    ) },
  { id: 'commodities', group: 'markets', icon: 'candles', render: (m) => <CommoditiesCard market={m} /> },
  { id: 'oil', group: 'markets', section: 'investor', icon: 'compare', markets: [...INDIA, 'us', 'hong_kong', 'china_a'],
    render: (m) => <CrudeSensitivity market={INDIA.includes(m) ? 'india' : m} /> },
]

function available(market: string, section: Section | null): Tab[] {
  return TABS.filter(
    (t) => (!t.markets || t.markets.includes(market)) && !t.except?.includes(market) && shows(section, t.section),
  )
}

const OPEN_KEY = 'marketmyna.insights.open'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode */
  }
}

/** The Markets page's insight sections as one tabbed panel under a clear
 * "Market insights" header with Show / Hide. The tab names stay visible even
 * when hidden, so nobody misses that the sections exist; picking a tab opens
 * the panel on it. Views are grouped (stocks, markets, economy) as chips that
 * wrap within their row, so labels never overlap and nothing hides off the edge. */
export default function MarketInsights({
  market,
  onCategory,
  markets,
  onMarket,
}: {
  market: string
  onCategory: (category: string) => void
  /** The page's market switch, repeated here so the views can change market in place. */
  markets?: Option[]
  onMarket?: (market: string) => void
}) {
  const { t } = useTranslation('markets')
  const section = useSection()
  const tabs = available(market, section)
  const [picked, setPicked] = useState<string>(() => read(TAB_KEY) || '')
  const [open, setOpen] = useState<boolean>(() => read(OPEN_KEY) !== '0')
  // Sections opened so far stay mounted (hidden) so switching back is instant.
  const [visited, setVisited] = useState<string[]>([])

  const active = tabs.some((tab) => tab.id === picked) ? picked : (tabs[0]?.id ?? '')
  const activeTab = tabs.find((tab) => tab.id === active)

  useEffect(() => {
    if (open && active && !visited.includes(active)) setVisited((v) => [...v, active])
  }, [open, active, visited])

  // A different market means different data: drop the hidden ones.
  useEffect(() => setVisited([]), [market])

  function choose(id: string) {
    setPicked(id)
    save(TAB_KEY, id)
    if (!open) toggle()
  }

  function toggle() {
    setOpen((o) => {
      save(OPEN_KEY, o ? '0' : '1')
      return !o
    })
  }

  return (
    <Card className="mb-6 overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Icon name="analyze" className="h-4 w-4 text-accent" />
            {t('insights.title')}
            <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">
              {t('insights.views', { count: tabs.length })}
            </span>
          </h2>
          <p className="text-xs text-muted">
            {open && activeTab
              ? t('insights.showing', { view: t(`insights.tabs.${activeTab.id}.inline`) })
              : t('insights.intro')}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={toggle} aria-expanded={open}>
          {open ? t('insights.hide') : t('insights.show')}
        </Button>
      </div>
      {markets && onMarket && (
        <div className="border-t border-line px-5 py-3">
          <Segmented options={markets} value={market} onChange={onMarket} size="sm" showHint />
        </div>
      )}
      <div role="tablist" aria-label={t('insights.title')} className={cx('space-y-2 border-t border-line px-5 py-3', open && 'border-b')}>
        {GROUPS.map((g) => {
          const items = tabs.filter((tab) => tab.group === g)
          if (!items.length) return null
          return (
            <div key={g} className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:gap-3">
              <div className="shrink-0 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint sm:w-20">{t(`insights.groups.${g}`)}</div>
              <div className="flex min-w-0 flex-wrap gap-1.5">
                {items.map((tab) => {
                  const selected = open && tab.id === active
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      onClick={() => choose(tab.id)}
                      className={cx(
                        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border px-2.5 py-1.5 text-[13px] font-medium transition-colors',
                        selected
                          ? 'border-accent/50 bg-accent-soft text-fg'
                          : 'border-line text-muted hover:border-line-strong hover:text-fg',
                      )}
                    >
                      <Icon name={tab.icon} className={cx('h-3.5 w-3.5', selected ? 'text-accent' : 'text-faint')} />
                      {t(`insights.tabs.${tab.id}.label`)}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
      {tabs
        .filter((tab) => visited.includes(tab.id) || (open && tab.id === active))
        .map((tab) => (
          <div key={`${market}:${tab.id}`} role="tabpanel" hidden={!open || tab.id !== active}>
            {/* Hidden panels stay mounted but stop refreshing their prices. */}
            <InsightActive.Provider value={open && tab.id === active}>{tab.render(market, onCategory)}</InsightActive.Provider>
          </div>
        ))}
    </Card>
  )
}
