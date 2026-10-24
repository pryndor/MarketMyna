import axios from 'axios'
import { saveBlob } from '../lib/files'
import { apiClient } from './client'

// The owner's profile, area and AI keys (single-user build: no login).
const accountClient = axios.create({ baseURL: '/api/auth/account' })

function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    return ''
  }
}

// Old names some browsers still report, mapped to the current IANA ones so
// the same place isn't listed (or saved) twice.
const ZONE_ALIASES: Record<string, string> = {
  'Asia/Calcutta': 'Asia/Kolkata',
  'Asia/Katmandu': 'Asia/Kathmandu',
  'Asia/Saigon': 'Asia/Ho_Chi_Minh',
  'Asia/Rangoon': 'Asia/Yangon',
  'Europe/Kiev': 'Europe/Kyiv',
  'America/Buenos_Aires': 'America/Argentina/Buenos_Aires',
  'America/Indianapolis': 'America/Indiana/Indianapolis',
  'Atlantic/Faeroe': 'Atlantic/Faroe',
  'Pacific/Truk': 'Pacific/Chuuk',
  'Pacific/Ponape': 'Pacific/Pohnpei',
}

export function canonicalZone(zone: string): string {
  return ZONE_ALIASES[zone] ?? zone
}

/** This device's time zone from its clock settings ('' if the browser won't say). */
export function deviceTimeZone(): string {
  return canonicalZone(browserTimeZone())
}

/** Everything is on in the self-hosted build; the shape is kept for the pages that read it. */
export type Plan = {
  id: string
  name: string
  description: string
  ai_calls_month: number | null
  limits: {
    watchlist_symbols: number | null
    price_alerts: number | null
    scheduled_runs_day: number | null
    portfolios: number | null
  }
  features: Record<string, unknown>
}

export type Me = {
  id: number
  email: string
  name: string
  role: 'user' | 'admin'
  /** The area the menus and pages follow; null shows both. */
  area: 'trader' | 'investor' | null
  /** IANA time zone; scheduled report times are in it. */
  timezone?: string
  /** The zone follows the device the app is opened on (deviceTimeZone). */
  timezone_auto?: boolean
  /** Always 'analytics': no calls, targets or stops on screen (src/core/compliance.py). */
  compliance: 'analytics'
  plan: Plan
}

export type ApiKey = {
  id: number
  provider: string
  last4: string
  /** Model picked for the key when it was saved (null = provider default). */
  model: string | null
  /** true: free access only; false: billed; null: unknown. */
  free: boolean | null
  note: string | null
  added_at: string | null
}
/** keys: in the order AI tries them. errors: keys from the last save that were refused. */
export type ApiKeys = { providers: string[]; keys: ApiKey[]; errors?: string[] }

export async function chooseArea(area: 'trader' | 'investor'): Promise<Me> {
  return (await accountClient.post<Me>('/area', { area })).data
}

export async function updateProfile(patch: { name?: string; timezone?: string; timezone_auto?: boolean }): Promise<Me> {
  return (await accountClient.patch<Me>('/profile', patch)).data
}

export async function getMe(): Promise<Me> {
  return (await accountClient.get<Me>('/me')).data
}

/** Downloads everything the app stores as JSON. */
export async function downloadMyData(): Promise<void> {
  const res = await accountClient.get('/export', { responseType: 'blob', timeout: 60_000 })
  const name = /filename="([^"]+)"/.exec(res.headers['content-disposition'] ?? '')?.[1] ?? 'marketmyna-data.json'
  saveBlob(res.data as Blob, name)
}

export async function getApiKeys(): Promise<ApiKeys> {
  return (await accountClient.get<ApiKeys>('/api-keys')).data
}

/** Saves one key or several (new lines, spaces or commas between them); the
 * server works out each key's provider and model. */
export async function putApiKey(key: string): Promise<ApiKeys> {
  return (await accountClient.put<ApiKeys>('/api-keys', { key })).data
}

export async function deleteApiKey(id: number): Promise<ApiKeys> {
  return (await accountClient.delete<ApiKeys>(`/api-keys/${id}`)).data
}

/* ------------------------------------------------------------------ data sources */

export type IntegrationField = {
  name: string
  label: string
  kind: 'text' | 'secret' | 'bool'
  from_env: boolean
  value?: string | number | boolean | null
  is_set?: boolean
  last4?: string
}

export type Integrations = {
  groups: { id: string; title: string; help: string; fields: IntegrationField[] }[]
}

export async function getIntegrations(): Promise<Integrations> {
  return (await apiClient.get<Integrations>('/system-config/data-sources')).data
}

export async function updateIntegrations(body: Record<string, unknown>): Promise<Integrations> {
  return (await apiClient.put<Integrations>('/system-config/data-sources', body)).data
}

export async function testIntegration(groupId: string): Promise<{ ok: boolean; message: string }> {
  return (await apiClient.post(`/system-config/data-sources/${groupId}/test`)).data
}
