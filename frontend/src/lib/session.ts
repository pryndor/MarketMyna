import { create } from 'zustand'
import { getAuthStatus } from '../api/auth'
import { deviceTimeZone, getMe, updateProfile, type Me } from '../api/account'

type SessionStore = {
  loaded: boolean
  me: Me | null
  /** Re-reads the signed-in user (null when signed out). */
  refresh: () => Promise<void>
  setMe: (me: Me | null) => void
}

export const useSession = create<SessionStore>((set) => ({
  loaded: false,
  me: null,
  refresh: async () => {
    try {
      const status = await getAuthStatus()
      const me = status.authenticated ? await getMe().catch(() => null) : null
      set({ loaded: true, me: me && (await followDeviceZone(me)) })
    } catch {
      // Backend unreachable: keep a session we already had (a blip), otherwise
      // stay logged out - never assume access.
      set((s) => (s.loaded ? {} : { loaded: true, me: null }))
    }
  },
  setMe: (me) => set({ me }),
}))

/** With "Set automatically" on, the account's time zone tracks the device it
 * is used from (travel, a laptop in another country), so scheduled reports
 * keep arriving at local times. A failed update keeps the saved zone. */
async function followDeviceZone(me: Me): Promise<Me> {
  const zone = deviceTimeZone()
  if (me.timezone_auto === false || !zone || zone === me.timezone) return me
  return updateProfile({ timezone: zone }).catch(() => me)
}

