import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
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
import { AreaLayout, NavGroup, NavItem } from './AreaNav'
import { Card, type IconName } from './ui'

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

/** The Markets page as one area: a menu on the side (a scrolling row on
 * phones) switches the area between the listings table and each view, so
 * nothing opens above the table and pushes it away. The market is picked once,
 * above, for the whole page; a view that points at a category (a sector in
 * Market pulse) opens the table filtered to it. */
export default function MarketArea({
  market,
  view,
  onView,
  onCategory,
  list,
}: {
  market: string
  /** 'list' or a view id; one the market lacks falls back to the list. */
  view: string
  onView: (view: string) => void
  onCategory: (category: string) => void
  /** The listings table and its controls. */
  list: ReactNode
}) {
  const { t } = useTranslation('markets')
  const section = useSection()
  const tabs = available(market, section)
  const active = tabs.some((tab) => tab.id === view) ? view : 'list'
  // Views opened so far stay mounted (hidden) so switching back is instant.
  const [visited, setVisited] = useState<string[]>([])

  useEffect(() => {
    if (active !== 'list' && !visited.includes(active)) setVisited((v) => [...v, active])
  }, [active, visited])

  // A different market means different data: drop the hidden ones.
  useEffect(() => setVisited([]), [market])

  function nav(rail: boolean) {
    return (
      <>
        <NavItem rail={rail} selected={active === 'list'} icon="grid" label={t('insights.list')} onClick={() => onView('list')} />
        {GROUPS.map((g) => {
          const items = tabs.filter((tab) => tab.group === g)
          if (!items.length) return null
          return (
            <NavGroup key={g} rail={rail} label={t(`insights.groups.${g}`)}>
              {items.map((tab) => (
                <NavItem
                  key={tab.id}
                  rail={rail}
                  selected={tab.id === active}
                  icon={tab.icon}
                  label={t(`insights.tabs.${tab.id}.label`)}
                  onClick={() => onView(tab.id)}
                />
              ))}
            </NavGroup>
          )
        })}
      </>
    )
  }

  return (
    <AreaLayout label={t('insights.title')} nav={nav}>
      <div hidden={active !== 'list'}>{list}</div>
      {tabs
        .filter((tab) => visited.includes(tab.id) || tab.id === active)
        .map((tab) => (
          <div key={`${market}:${tab.id}`} hidden={tab.id !== active}>
            <Card className="overflow-hidden">
              {/* Hidden views stay mounted but stop refreshing their prices. */}
              <InsightActive.Provider value={tab.id === active}>{tab.render(market, onCategory)}</InsightActive.Provider>
            </Card>
          </div>
        ))}
    </AreaLayout>
  )
}
