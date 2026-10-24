import { useEffect, useState, useSyncExternalStore } from 'react'
import { apiClient } from '../api/client'

/** Opt-in English for Chinese names (China A stocks, block-trade brokers).
 * One preference for the whole app, remembered in this browser; translations
 * are cached here and on the server, so each name is looked up once. */

const KEY = 'marketmyna.english-names'
const EVENT = 'marketmyna:english-names'
const CJK = /[㐀-鿿]/

export const hasChinese = (text: string | null | undefined) => !!text && CJK.test(text)

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setEnglish(on: boolean) {
  try {
    localStorage.setItem(KEY, on ? '1' : '0')
  } catch {
    /* private mode */
  }
  window.dispatchEvent(new Event(EVENT))
}

export function useEnglish(): boolean {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener(EVENT, cb)
      window.addEventListener('storage', cb)
      return () => {
        window.removeEventListener(EVENT, cb)
        window.removeEventListener('storage', cb)
      }
    },
    read,
    () => false,
  )
}

const nameCache = new Map<string, string>()
const textCache = new Map<string, string>()

/** English for the Chinese names/texts given, while the preference is on.
 * Returns lookups that fall back to the original until the answer arrives. */
export function useEnglishNames(
  market: string,
  names: Array<{ symbol: string; name: string | null | undefined }>,
  texts: Array<string | null | undefined> = [],
) {
  const on = useEnglish()
  const [, bump] = useState(0)
  const wantNames = on ? names.filter((n) => hasChinese(n.name) && !nameCache.has(`${market}:${n.symbol}`)) : []
  const wantTexts = on ? [...new Set(texts.filter((t): t is string => hasChinese(t) && !textCache.has(t!)))] : []
  const key = wantNames.map((n) => n.symbol).join(',') + '|' + wantTexts.join('|')

  useEffect(() => {
    if (!wantNames.length && !wantTexts.length) return
    let live = true
    apiClient
      .post<{ names: Record<string, string>; texts: Record<string, string> }>(
        '/translate',
        { market, names: wantNames.map((n) => ({ symbol: n.symbol, name: n.name })), texts: wantTexts },
        { timeout: 90_000 },
      )
      .then(({ data }) => {
        for (const [s, en] of Object.entries(data.names)) nameCache.set(`${market}:${s}`, en)
        for (const [zh, en] of Object.entries(data.texts)) textCache.set(zh, en)
        if (live) bump((n) => n + 1)
      })
      .catch(() => undefined)
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, key])

  return {
    on,
    loading: wantNames.length + wantTexts.length > 0,
    name: (symbol: string, original: string | null | undefined) =>
      (on && hasChinese(original) && nameCache.get(`${market}:${symbol}`)) || original || symbol,
    text: (original: string | null | undefined) => (on && original && textCache.get(original)) || original || '',
  }
}
