import { useEffect, type ReactNode } from 'react'
import { Outlet } from 'react-router-dom'
import type { Section } from '../lib/section'
import { useSession } from '../lib/session'
import { Skeleton } from './ui'

/** Loads the local owner once, then renders the router. Single-user build:
 * there is no login; every request runs as the owner (api/middlewares/auth.py). */
export default function AuthGate({ children }: { children: ReactNode }) {
  const { loaded, refresh } = useSession()

  useEffect(() => {
    refresh()
  }, [refresh])

  if (!loaded) return <Skeleton className="m-8 h-96" />
  return <>{children}</>
}

/** Route guard for the app pages: waits for the backend instead of a login page. */
export function RequireAccount() {
  const me = useSession((s) => s.me)
  const refresh = useSession((s) => s.refresh)
  if (!me) {
    return (
      <div className="mx-auto max-w-md p-8 text-center text-sm text-muted">
        <p>The MarketMyna API isn't reachable. Start it, then try again.</p>
        <button type="button" onClick={() => refresh()} className="mt-4 rounded-lg bg-accent px-4 py-2 font-medium text-white">
          Try again
        </button>
      </div>
    )
  }
  return <Outlet />
}

/** The owner is the admin and can open every page in both areas. */
export function RequireArea(_props: { area: Section }) {
  return <Outlet />
}
