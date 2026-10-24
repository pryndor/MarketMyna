import { isAxiosError } from 'axios'
import i18n from '../i18n'
import { languageInfo, type Language } from '../i18n/languages'

/** Pulls the human-readable message out of the API's error envelope
 * ({error, message, detail}), falling back to the transport error. */
export function errorMessage(err: unknown): string {
  if (isAxiosError(err)) {
    const data = err.response?.data as { message?: string } | undefined
    if (data?.message) return data.message
    if (!err.response) return 'Cannot reach the MarketMyna API. Is the backend running on :8000?'
    return `HTTP ${err.response.status}`
  }
  return err instanceof Error ? err.message : String(err)
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function money(value: number | null | undefined, currency?: string): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (!currency) return num(value)
  try {
    return value.toLocaleString(undefined, { style: 'currency', currency })
  } catch {
    return `${num(value)} ${currency}`
  }
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : ''}${num(value, digits)}`
}

export function pct(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${signed(value, digits)}%`
}

/** 1_234_567 -> 1.23M */
export function compact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toLocaleString(undefined, { notation: 'compact', maximumFractionDigits: 2 })
}

/** A timestamp from the server as a Date. The server keeps times in UTC
 * without a zone marker ("2026-10-13T05:47:00"), which a browser would read
 * as its own local time (5 h 30 min off in India); those are read as UTC.
 * Times with "Z" or an offset, and plain dates, are left as they are. Only for
 * server event times (seen, created, run), not market bar dates. */
export function serverTime(iso: string): Date {
  return new Date(/T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(iso) ? `${iso}Z` : iso)
}

/** "27m ago" in the chosen language (Western digits everywhere, as elsewhere in the app). */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return i18n.t('app:time.never')
  const then = serverTime(iso).getTime()
  if (Number.isNaN(then)) return iso
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 60) return i18n.t('app:time.justNow')
  const tag = `${languageInfo(i18n.language as Language).tag}-u-nu-latn`
  // English keeps the terse "27m ago"; other languages read better with the short words.
  const words = new Intl.RelativeTimeFormat(tag, { style: i18n.language === 'en' ? 'narrow' : 'short' })
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return words.format(-minutes, 'minute')
  const hours = Math.round(minutes / 60)
  if (hours < 48) return words.format(-hours, 'hour')
  return serverTime(iso).toLocaleDateString()
}

export function trendClass(value: number | null | undefined): string {
  if (value == null || value === 0) return 'text-muted'
  return value > 0 ? 'text-up' : 'text-down'
}

/** Market cap in the listing's own convention: ₹ crores for INR (as
 * Indian screeners show it), compact notation otherwise. */
export function marketCap(value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (currency === 'INR') return `${Math.round(value / 1e7).toLocaleString('en-IN')} Cr`
  return compact(value)
}

const SYMBOLS: Record<string, string> = { INR: '₹', USD: '$', CNY: '¥', HKD: 'HK$' }

export function price(value: number | null | undefined, currency?: string | null): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const digits = Math.abs(value) < 1 ? 4 : 2
  const n = currency === 'INR' ? value.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : num(value, digits)
  return `${(currency && SYMBOLS[currency]) ?? ''}${n}`
}

/** Initials for the avatar: "Bala Krishnan" -> BK, else the email's first letter. */
export function initials(name: string, email: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length) return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
  return (email[0] ?? '?').toUpperCase()
}
