import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AuthGate, { RequireAccount, RequireArea } from './components/AuthGate'
import Layout from './components/Layout'
import RouteMeta from './components/RouteMeta'
import { Skeleton } from './components/ui'

// One chunk per page - recharts only loads with Analyze.
const AnalyzePage = lazy(() => import('./pages/Analyze'))
const MarketsPage = lazy(() => import('./pages/Markets'))
const WatchlistPage = lazy(() => import('./pages/Watchlist'))
const BotPage = lazy(() => import('./pages/Bot'))
const PortfolioPage = lazy(() => import('./pages/Portfolio'))
const SchedulerPage = lazy(() => import('./pages/Scheduler'))
const SettingsPage = lazy(() => import('./pages/Settings'))
const ReportViewPage = lazy(() => import('./pages/ReportView'))
const TradePage = lazy(() => import('./pages/Trade'))
const ComparePage = lazy(() => import('./pages/Compare'))
const AccountPage = lazy(() => import('./pages/Account'))

function App() {
  return (
    <AuthGate>
      <BrowserRouter>
        <RouteMeta />
        <Suspense fallback={<Skeleton className="m-8 h-96" />}>
          <Routes>
            {/* Single-user build: no login, sign-up or pricing pages. */}
            <Route element={<RequireAccount />}>
              <Route element={<Layout />}>
                <Route index element={<MarketsPage />} />
                <Route path="analyze" element={<AnalyzePage />} />
                <Route element={<RequireArea area="trader" />}>
                  <Route path="trade" element={<TradePage />} />
                </Route>
                <Route path="watchlist" element={<WatchlistPage />} />
                <Route element={<RequireArea area="investor" />}>
                  <Route path="portfolio" element={<PortfolioPage />} />
                  <Route path="compare" element={<ComparePage />} />
                </Route>
                {/* Both areas: each sees its own report sections (ReportSettings). */}
                <Route path="scheduler" element={<SchedulerPage />} />
                <Route path="bot" element={<BotPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="account" element={<AccountPage />} />
                <Route path="r/:token" element={<ReportViewPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthGate>
  )
}

export default App
