import { apiClient } from './client'

export type EventKind = 'earnings' | 'ex_dividend' | 'dividend' | 'board_meeting' | 'corporate_action'

export interface CalendarEvent {
  symbol: string
  market: string
  kind: EventKind
  label: string
  date: string
  days_away: number
  followed_in: string[]
  eps_estimate?: number | null
  revenue_estimate?: number | null
  /** from the exchange: "Board meeting: results, dividend", "Interim Dividend - Rs 3 Per Share" */
  detail?: string
  /** the date is the exchange's own, not an estimate */
  confirmed?: boolean
}

export interface CalendarSettings {
  notify: boolean
  days_before: number
  notify_hour: number
  timezone: string
  /** event type keys turned off (hidden from the list and the reminder) */
  hidden_events: string[]
  /** "My events list": lists that count ("w:<id>" / "p:<id>"); null = every list */
  sources: string[] | null
  /** stocks followed just for events */
  extra_symbols: EventSymbol[]
}

export interface EventSymbol {
  symbol: string
  market: string
}

/** A watchlist or portfolio that can feed events. */
export interface EventList {
  id: string
  kind: 'watchlist' | 'portfolio'
  name: string
  count: number
}

/** A named alert: its own stocks, event types and send time, one message per run. */
export interface EventAlert {
  id: number
  name: string
  enabled: boolean
  /** null = every list, [] = only `symbols` */
  sources: string[] | null
  symbols: EventSymbol[]
  /** null = every event type */
  event_types: string[] | null
  days_before: number
  notify_hour: number
  notified_day: string | null
}

export type Repeat = 'none' | 'monthly' | 'yearly'

export interface CustomEvent {
  id: number
  title: string
  /** first (or only) date */
  date: string
  repeat: Repeat
  note: string
}

/** One occurrence of a custom event inside the window. */
export interface CustomOccurrence extends CustomEvent {
  first_date: string
  days_away: number
  kind: 'custom'
}

export interface EventType {
  key: string
  group: 'stocks' | 'us' | 'india' | 'markets' | 'mine'
  name: string
  about: string
}

export interface EconomicEvent {
  date: string
  time: string | null
  tz: string | null
  local_time: string | null
  title: string
  region: 'US' | 'India' | 'Hong Kong' | 'China' | 'Global'
  /** 'market': a holiday, short day, special session, expiry, index review or clock change (see `key`) */
  kind: 'central_bank' | 'inflation' | 'jobs' | 'growth' | 'spending' | 'market'
  importance: 'high' | 'medium'
  note: string
  source: string
  estimated: boolean
  days_away: number
  key?: string
  /** latest published reading, e.g. "3.7% YoY in Aug, up from 3.5%; core 2.8%" */
  last?: string | null
  /** how a surprise usually moves stocks */
  why?: string | null
  /** followed stocks listed in this event's country */
  exposure?: string[]
  /** today's new number once the release is out, and what it means */
  result?: string
  verdict?: string
}

export interface CalendarResponse {
  from: string
  days: number
  symbols: number
  events: CalendarEvent[]
  economic?: EconomicEvent[]
  economic_warnings?: string[]
  event_types?: EventType[]
  custom?: CustomOccurrence[]
  custom_all?: CustomEvent[]
  lists?: EventList[]
  alerts?: EventAlert[]
  settings: CalendarSettings
}

export async function getCalendar(days = 30): Promise<CalendarResponse> {
  return (await apiClient.get<CalendarResponse>('/calendar', { params: { days } })).data
}

export async function saveCalendarSettings(patch: Partial<CalendarSettings> & { all_lists?: boolean }): Promise<CalendarSettings> {
  return (await apiClient.put<CalendarSettings>('/calendar/settings', patch)).data
}

export async function sendCalendarDigest(): Promise<Sent> {
  return (await apiClient.post<Sent>('/calendar/remind-now')).data
}

/** The toast after a manual send. */
export function sentMessage(res: Sent): { tone: 'success' | 'info'; text: string } {
  if (!res.sent) return { tone: 'info', text: 'Nothing due in the reminder window' }
  const ok = Object.values(res.delivery ?? {}).filter(Boolean).length
  if (!ok) return { tone: 'info', text: `${res.count} event${res.count === 1 ? '' : 's'} found, but no alert channel delivered it - set one up in Settings → Notifications` }
  return { tone: 'success', text: `Sent ${res.count} event${res.count === 1 ? '' : 's'}` }
}

/** delivery: channel -> delivered; empty when the user has no alert channel set up */
type Sent = { sent: boolean; count: number; delivery?: Record<string, boolean> }

export type AlertPatch = Partial<Omit<EventAlert, 'id' | 'notified_day'>> & { all_types?: boolean; all_lists?: boolean }

export async function createEventAlert(alert: AlertPatch): Promise<EventAlert> {
  return (await apiClient.post<EventAlert>('/calendar/alerts', alert)).data
}

export async function updateEventAlert(id: number, patch: AlertPatch): Promise<EventAlert> {
  return (await apiClient.put<EventAlert>(`/calendar/alerts/${id}`, patch)).data
}

export async function deleteEventAlert(id: number): Promise<void> {
  await apiClient.delete(`/calendar/alerts/${id}`)
}

export async function sendEventAlert(id: number): Promise<Sent> {
  return (await apiClient.post<Sent>(`/calendar/alerts/${id}/send-now`)).data
}

export async function createCustomEvent(event: Omit<CustomEvent, 'id'>): Promise<CustomEvent> {
  return (await apiClient.post<CustomEvent>('/calendar/custom-events', event)).data
}

export async function deleteCustomEvent(id: number): Promise<void> {
  await apiClient.delete(`/calendar/custom-events/${id}`)
}
