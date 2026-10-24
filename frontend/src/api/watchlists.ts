import { apiClient } from './client'
import type { Listing, ListingType } from './listings'

export interface WatchlistSummary {
  id: number
  name: string
  count: number
}

/** Saved item plus (when the symbol is in the market listing) its live fields. */
export interface WatchlistItem extends Partial<Omit<Listing, 'symbol' | 'market' | 'type' | 'name'>> {
  id: number
  watchlist_id: number
  symbol: string
  market: string
  type: ListingType
  name: string
  note: string
  added_at: string | null
  listed: boolean
}

export interface WatchlistDetail extends WatchlistSummary {
  items: WatchlistItem[]
}

export interface Membership {
  id: number
  watchlist_id: number
  symbol: string
  market: string
  type: string
}

export interface NewItem {
  symbol: string
  market: string
  type: string
  name?: string
}

export async function listWatchlists(): Promise<WatchlistSummary[]> {
  return (await apiClient.get<WatchlistSummary[]>('/watchlists')).data
}

export async function getWatchlist(id: number): Promise<WatchlistDetail> {
  return (await apiClient.get<WatchlistDetail>(`/watchlists/${id}`)).data
}

export async function createWatchlist(name: string): Promise<WatchlistSummary> {
  return (await apiClient.post<WatchlistSummary>('/watchlists', { name })).data
}

export async function renameWatchlist(id: number, name: string): Promise<WatchlistSummary> {
  return (await apiClient.patch<WatchlistSummary>(`/watchlists/${id}`, { name })).data
}

export async function deleteWatchlist(id: number): Promise<void> {
  await apiClient.delete(`/watchlists/${id}`)
}

export async function listMemberships(): Promise<Membership[]> {
  return (await apiClient.get<Membership[]>('/watchlists/items')).data
}

export async function addWatchlistItem(id: number, item: NewItem): Promise<Membership> {
  return (await apiClient.post<Membership>(`/watchlists/${id}/items`, item)).data
}

export async function removeWatchlistItem(id: number, itemId: number): Promise<void> {
  await apiClient.delete(`/watchlists/${id}/items/${itemId}`)
}
