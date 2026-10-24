import { Suspense, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { apiClient } from '../api/client'
import { getSchedulerStatus } from '../api/scheduler'
import { getUpdateStatus } from '../api/updates'
import { Icon, Skeleton, StatusDot, type IconName } from './ui'
import { cx } from '../lib/cx'
import { Toaster } from './Toaster'
import { setTheme, useTheme } from '../lib/theme'
import { useSession } from '../lib/session'
import { SECTIONS, shows, useSection, type Section } from '../lib/section'
import { chooseArea } from '../api/account'
import { errorMessage, initials } from '../lib/format'
import { toast } from '../lib/toast'
import Logo from './Logo'
import ThemeToggle from './ThemeToggle'
import LanguagePicker from './LanguagePicker'

function Brand({ showName = true }: { showName?: boolean }) {
  return (
    <>
      <Logo className="h-8 w-8 shrink-0" />
      {showName && <span className="text-[15px] font-semibold tracking-tight">MarketMyna</span>}
    </>
  )
}

/** section: shown only in that side of the app (untagged = both). */
type NavKey = 'markets' | 'watchlist' | 'analyze' | 'trade' | 'portfolio' | 'compare' | 'scheduler' | 'bot' | 'settings' | 'account'
type NavItem = { to: string; key: NavKey; label: string; short: string; icon: IconName; end?: boolean; section?: Section }
type NavDef = Omit<NavItem, 'label' | 'short'>

// The first PRIMARY_COUNT items are the phone's bottom tab bar; the rest sit
// behind its "More" sheet. Tablet rail and desktop sidebar show all of them.
const NAV: NavDef[] = [
  { to: '/', key: 'markets', icon: 'globe', end: true },
  { to: '/watchlist', key: 'watchlist', icon: 'star' },
  { to: '/analyze', key: 'analyze', icon: 'analyze' },
  { to: '/trade', key: 'trade', icon: 'candles', section: 'trader' },
  { to: '/portfolio', key: 'portfolio', icon: 'portfolio', section: 'investor' },
  { to: '/compare', key: 'compare', icon: 'compare', section: 'investor' },
  { to: '/scheduler', key: 'scheduler', icon: 'clock' },
  { to: '/bot', key: 'bot', icon: 'chat' },
  { to: '/settings', key: 'settings', icon: 'settings' },
]
const PRIMARY_COUNT = 4

/** NAV for the user's section, plus the account page. */
function useNav(): NavItem[] {
  const { t } = useTranslation('app')
  const section = useSection()
  const extra: NavDef[] = [{ to: '/account', key: 'account', icon: 'user' }]
  const visible = NAV.filter((item) => shows(section, item.section))
  return [...visible, ...extra].map((item) => ({ ...item, label: t(`nav.${item.key}.label`), short: t(`nav.${item.key}.short`) }))
}

type Health = 'checking' | 'online' | 'offline'

/** Polls API + scheduler liveness so every page shows whether the
 * backend it's talking to is actually up. One failed check is ignored (a
 * blip); while offline it checks every few seconds, so the banner clears
 * as soon as the API is back (a deploy restarts it for ~30-60 s). */
function useBackendStatus() {
  const [api, setApi] = useState<Health>('checking')
  const [scheduler, setScheduler] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    let failures = 0
    let timer: number | undefined
    let busy = false
    async function check() {
      if (busy) return
      busy = true
      window.clearTimeout(timer)
      try {
        await apiClient.get('/health', { timeout: 10_000 })
        if (cancelled) return
        failures = 0
        setApi('online')
        const status = await getSchedulerStatus()
        if (!cancelled) setScheduler(status.running && status.schedule.enabled)
      } catch {
        if (cancelled) return
        failures += 1
        if (failures >= 2) {
          setApi('offline')
          setScheduler(null)
        }
      }
      busy = false
      if (!cancelled) timer = window.setTimeout(check, failures ? 5_000 : 30_000)
    }
    const onFocus = () => {
      if (document.visibilityState === 'visible') check()
    }
    check()
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [])

  return { api, scheduler }
}

/** Who is signed in: avatar, name and email, linking to Account settings. */
function UserChip({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation('app')
  const me = useSession((s) => s.me)
  if (!me) return null
  const label = me.name || me.email
  return (
    <Link
      to="/account"
      title={t('user.title', { name: label, email: me.email })}
      className={cx('flex min-w-0 items-center gap-2.5 rounded-lg text-start hover:text-fg', !compact && '-mx-2 px-2 py-1.5 hover:bg-raised/60')}
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-fg ring-1 ring-accent/30">
        {initials(me.name, me.email)}
      </span>
      {!compact && (
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-fg">{label}</span>
          <span className="block truncate text-[11px] text-muted">{me.name ? me.email : t('user.plan', { plan: me.plan.name })}</span>
        </span>
      )}
    </Link>
  )
}

/** Whether the server's own GitHub check (Settings -> Updates) found a new
 * version. Reads its last result once a minute; never calls GitHub itself. */
function useUpdateAvailable(): boolean {
  const admin = useSession((s) => s.me?.role === 'admin')
  const [available, setAvailable] = useState(false)
  useEffect(() => {
    if (!admin) return
    let cancelled = false
    const load = () =>
      getUpdateStatus()
        .then((s) => !cancelled && setAvailable(Boolean(s.update_available)))
        .catch(() => {})
    load()
    const timer = window.setInterval(load, 60_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [admin])
  return available
}

function StatusLines({ api, scheduler }: { api: Health; scheduler: boolean | null }) {
  const { t } = useTranslation('app')
  const update = useUpdateAvailable()
  return (
    <>
      {update && (
        <Link to="/settings" className="flex items-center gap-2 font-medium text-accent-fg hover:underline">
          <StatusDot tone="accent" />
          {t('status.update')}
        </Link>
      )}
      <div className="flex items-center gap-2">
        <StatusDot tone={api === 'online' ? 'up' : api === 'offline' ? 'down' : 'neutral'} />
        {t(`status.api.${api}`)}
      </div>
      <div className="flex items-center gap-2">
        <StatusDot tone={scheduler ? 'up' : 'neutral'} />
        {t(`status.schedule.${scheduler == null ? 'unknown' : scheduler ? 'active' : 'off'}`)}
      </div>
    </>
  )
}

/** Phone only: fixed icon tab bar for the main pages plus a "More" button. */
function BottomNav({ onMore, moreActive }: { onMore: () => void; moreActive: boolean }) {
  const { t } = useTranslation('app')
  const NAV = useNav()
  const tab = (active: boolean) =>
    cx(
      'flex min-w-0 flex-col items-center justify-center gap-1 pt-2 pb-1.5 text-[11px] font-medium transition-colors',
      active ? 'text-accent-fg' : 'text-muted active:text-fg',
    )
  const pill = (active: boolean) =>
    cx('grid h-8 w-14 place-items-center rounded-full transition-colors', active && 'bg-accent-soft')
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-line bg-sidebar/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
      aria-label={t('mainNav')}
    >
      {NAV.slice(0, PRIMARY_COUNT).map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => tab(isActive)}>
          {({ isActive }) => (
            <>
              <span className={pill(isActive)}>
                <Icon name={item.icon} className="h-5 w-5" />
              </span>
              <span className="truncate">{item.short}</span>
            </>
          )}
        </NavLink>
      ))}
      <button type="button" onClick={onMore} className={tab(moreActive)} aria-haspopup="dialog">
        <span className={pill(moreActive)}>
          <Icon name="grid" className="h-5 w-5" />
        </span>
        {t('more')}
      </button>
    </nav>
  )
}

/** Phone only: bottom sheet with the remaining pages and the sidebar extras. */
function MoreSheet({ open, onClose, api, scheduler }: { open: boolean; onClose: () => void; api: Health; scheduler: boolean | null }) {
  const { t } = useTranslation('app')
  const NAV = useNav()
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label={t('more')}>
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-line bg-surface px-4 pt-3 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-2xl">
        <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-line-strong" />
        <AreaControl className="mb-4" onSwitch={onClose} />
        <div className="grid grid-cols-4 gap-2">
          {NAV.slice(PRIMARY_COUNT).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onClose}
              className={({ isActive }) =>
                cx(
                  'flex flex-col items-center gap-1.5 rounded-xl px-1 py-3 text-xs font-medium transition-colors',
                  isActive ? 'bg-accent-soft text-accent-fg' : 'bg-raised text-fg active:bg-line',
                )
              }
            >
              <Icon name={item.icon} className="h-6 w-6" />
              <span className="truncate">{item.short}</span>
            </NavLink>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2">
          <ThemeRow />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line pt-3 text-xs text-muted">
          <StatusLines api={api} scheduler={scheduler} />
        </div>
      </div>
    </div>
  )
}

function ThemeRow() {
  const { t } = useTranslation('app')
  const theme = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className="flex items-center justify-center gap-2 rounded-xl bg-raised px-3 py-3 text-sm font-medium text-fg active:bg-line"
    >
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
      {theme === 'dark' ? t('lightMode') : t('darkMode')}
    </button>
  )
}

export default function Layout() {
  const { t } = useTranslation('app')
  const NAV = useNav()
  const { api, scheduler } = useBackendStatus()
  const { pathname } = useLocation()
  const [moreOpen, setMoreOpen] = useState(false)

  useEffect(() => setMoreOpen(false), [pathname])
  const moreActive = NAV.slice(PRIMARY_COUNT).some((item) => pathname.startsWith(item.to))

  return (
    <div className="min-h-screen md:flex">
      {/* Phone: slim sticky top bar. Navigation lives in the bottom tab bar. */}
      <header className="sticky top-0 z-30 flex items-center gap-2.5 border-b border-line bg-sidebar/95 px-4 pt-[max(0.625rem,env(safe-area-inset-top))] pb-2.5 backdrop-blur md:hidden">
        <Brand />
        <LanguagePicker className="ms-auto" />
        <ThemeToggle className="-me-2" />
      </header>

      {/* Tablet (md): icon rail with small labels. Desktop (lg): full sidebar. */}
      <aside className="hidden shrink-0 flex-col border-e border-line bg-sidebar md:sticky md:top-0 md:z-30 md:flex md:h-screen md:w-[84px] lg:w-56">
        <div className="flex items-center justify-center gap-2.5 py-5 lg:justify-start lg:px-5">
          <span className="lg:hidden" title="MarketMyna">
            <Brand showName={false} />
          </span>
          <span className="hidden items-center gap-2.5 lg:flex">
            <Brand />
          </span>
          <ThemeToggle className="ms-auto hidden lg:block" />
        </div>
        <AreaControl className="mx-2 mb-3 lg:mx-3" />

        <nav className="flex flex-col gap-1 overflow-y-auto px-2 lg:px-3" aria-label={t('mainNav')}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={item.label}
              className={({ isActive }) =>
                cx(
                  'flex flex-col items-center gap-1 rounded-xl px-1 py-2 text-[11px] font-medium transition-colors',
                  'lg:flex-row lg:gap-2.5 lg:rounded-lg lg:px-3 lg:text-sm',
                  isActive ? 'bg-accent-soft text-fg ring-1 ring-accent/40' : 'text-muted hover:bg-raised/60 hover:text-fg',
                )
              }
            >
              <Icon name={item.icon} className="h-5 w-5 lg:h-4 lg:w-4" />
              <span className="lg:hidden">{item.short}</span>
              <span className="hidden lg:inline">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto flex flex-col items-center gap-3 border-t border-line py-4 lg:hidden">
          <UserChip compact />
          <LanguagePicker compact />
          <ThemeToggle />
          <span title={t(`status.api.${api}`)}>
            <StatusDot tone={api === 'online' ? 'up' : api === 'offline' ? 'down' : 'neutral'} />
          </span>
        </div>
        <div className="mt-auto hidden space-y-2 border-t border-line px-5 py-4 text-xs text-muted lg:block">
          <UserChip />
          <LanguagePicker className="-mx-2" />
          <StatusLines api={api} scheduler={scheduler} />
        </div>
      </aside>

      <main className="min-w-0 flex-1 pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-0">
        {api === 'offline' && (
          <div className="border-b border-down/30 bg-down-soft px-4 py-2 text-sm text-down sm:px-6">
            {import.meta.env.DEV ? (
              <>
                MarketMyna API unreachable. Start it with <code className="font-mono">python -m uvicorn api.app:app --port 8001</code> (or set MARKETMYNA_API for another port).
              </>
            ) : (
              t('offline')
            )}
          </div>
        )}
        <div className="mx-auto max-w-screen-2xl px-4 py-5 sm:px-6 sm:py-6 lg:px-8 lg:py-8">
          <Suspense fallback={<Skeleton className="h-96 w-full" />}>
            <Outlet />
          </Suspense>
        </div>
      </main>
      <BottomNav onMore={() => setMoreOpen(true)} moreActive={moreActive || moreOpen} />
      <MoreSheet open={moreOpen} onClose={() => setMoreOpen(false)} api={api} scheduler={scheduler} />
      <Toaster />
    </div>
  )
}

/** The in-place Trader / Investor toggle (saved on the owner's account). */
function AreaControl(props: { className?: string; onSwitch?: () => void }) {
  return <AreaToggle className={props.className} />
}

/** Flips the menu and cards between the two areas on the spot. */
function AreaToggle({ className }: { className?: string }) {
  const { t } = useTranslation('app')
  const section = useSection()
  const setMe = useSession((s) => s.setMe)
  const [busy, setBusy] = useState(false)

  async function pick(next: Section) {
    if (next === section || busy) return
    setBusy(true)
    try {
      setMe(await chooseArea(next))
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  // The area you are in is filled with the accent and can't be clicked; the
  // other is an outlined button that shows the hand and says "Switch to".
  return (
    <div className={className}>
      <div className="mb-1 hidden px-1 text-[10px] font-semibold tracking-wide text-faint uppercase lg:block">{t('area.label')}</div>
      <div
        role="radiogroup"
        aria-label={t('area.label')}
        className="grid grid-cols-2 gap-1 rounded-lg border border-line p-1 md:grid-cols-1 lg:grid-cols-2"
      >
        {SECTIONS.map((s) => {
          const current = section === s.id
          const name = t(`area.${s.id}`)
          return (
            <button
              key={s.id}
              type="button"
              role="radio"
              aria-checked={current}
              disabled={busy}
              onClick={() => pick(s.id)}
              title={current ? t('area.youAreIn', { area: name }) : t('area.switchTo', { area: name })}
              className={cx(
                'flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-semibold transition-colors',
                current
                  ? 'cursor-default bg-accent text-white shadow-sm'
                  : 'cursor-pointer text-muted hover:bg-raised hover:text-fg',
              )}
            >
              <Icon name={current ? 'check' : s.icon} className="h-3.5 w-3.5" />
              <span className="md:hidden lg:inline">{name}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

