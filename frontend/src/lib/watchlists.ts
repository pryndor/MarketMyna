import { create } from 'zustand'
import {
  addWatchlistItem,
  createWatchlist,
  deleteWatchlist,
  listMemberships,
  listWatchlists,
  removeWatchlistItem,
  renameWatchlist,
  type Membership,
  type NewItem,
  type WatchlistSummary,
} from '../api/watchlists'
import { errorMessage } from './format'
import { toast } from './toast'

export function itemKey(item: { market: string; type: string; symbol: string }): string {
  return `${item.market}:${item.type}:${item.symbol}`
}

interface WatchlistStore {
  lists: WatchlistSummary[]
  members: Membership[]
  loaded: boolean
  /** Why the last load failed, so the Watchlist page can say so instead of spinning. */
  loadError: string | null
  /** Bumped on every change so open list pages know to refetch. */
  version: number
  load: () => Promise<void>
  add: (listId: number, item: NewItem) => Promise<void>
  remove: (listId: number, item: { market: string; type: string; symbol: string }) => Promise<void>
  create: (name: string) => Promise<WatchlistSummary | null>
  rename: (listId: number, name: string) => Promise<void>
  destroy: (listId: number) => Promise<void>
}

/** App-wide watchlist state, shared by every star button and the
 * Watchlist page so they never disagree. */
export const useWatchlists = create<WatchlistStore>((set, get) => {
  async function refresh() {
    const [lists, members] = await Promise.all([listWatchlists(), listMemberships()])
    set((s) => ({ lists, members, loaded: true, version: s.version + 1 }))
  }

  async function run(action: () => Promise<unknown>, success?: string) {
    try {
      await action()
      await refresh()
      if (success) toast.success(success)
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  // Every star button asks to load on mount; share one request instead of
  // firing a pair per row (a Markets page has 50 of them).
  let inflight: Promise<void> | null = null

  return {
    lists: [],
    members: [],
    loaded: false,
    loadError: null,
    version: 0,
    load: () => {
      inflight ??= refresh()
        .then(() => set({ loadError: null }))
        .catch((err) => {
          // API offline - Layout already shows a banner; stars just stay empty.
          set({ loadError: errorMessage(err) })
        })
        .finally(() => {
          inflight = null
        })
      return inflight
    },
    add: (listId, item) => {
      const list = get().lists.find((l) => l.id === listId)
      return run(() => addWatchlistItem(listId, item), `${item.symbol} added to ${list?.name ?? 'watchlist'}`)
    },
    remove: (listId, item) => {
      const member = get().members.find((m) => m.watchlist_id === listId && itemKey(m) === itemKey(item))
      if (!member) return Promise.resolve()
      const list = get().lists.find((l) => l.id === listId)
      return run(() => removeWatchlistItem(listId, member.id), `${item.symbol} removed from ${list?.name ?? 'watchlist'}`)
    },
    create: async (name) => {
      try {
        const created = await createWatchlist(name)
        await refresh()
        return created
      } catch (err) {
        toast.error(errorMessage(err))
        return null
      }
    },
    rename: (listId, name) => run(() => renameWatchlist(listId, name)),
    destroy: (listId) => run(() => deleteWatchlist(listId), 'Watchlist deleted'),
  }
})
