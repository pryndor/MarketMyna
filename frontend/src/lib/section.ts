import type { IconName } from '../components/ui'
import { useSession } from './session'

/** The two areas of the app. Both use the same login; the area is chosen at
 * login (each area can later have its own plan). Menus, pages, Analyze
 * cards and Markets insights follow the area of the current login. */
export type Section = 'trader' | 'investor'

export const SECTIONS: { id: Section; icon: IconName }[] = [
  { id: 'trader', icon: 'candles' },
  { id: 'investor', icon: 'portfolio' },
]

/** The area of the current login, or null until one is chosen. */
export function useSection(): Section | null {
  return useSession((s) => s.me?.area ?? null)
}

/** Whether something tagged for `only` shows in `section` (untagged = both areas). */
export function shows(section: Section | null, only?: Section): boolean {
  return !only || !section || only === section
}
