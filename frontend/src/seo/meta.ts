import pages from './pages.json'

// The browser tab title per app page (RouteMeta), from pages.json.
const APP = pages.app as Record<string, string>

export function titleFor(pathname: string): string {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  const name = APP[path] ?? (path.startsWith('/r/') ? 'Shared report' : null)
  return name ? `${name} | MarketMyna` : 'MarketMyna'
}
