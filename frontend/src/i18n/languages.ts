// The languages MarketMyna is offered in. `code` is the folder under
// src/i18n/locales and the stored choice; `tag` goes on <html lang> (and,
// later, hreflang); `name` is how the language calls itself, so a visitor
// finds theirs in the picker whatever language the page is in now.
// public/theme-init.js keeps its own copy of the codes and RTL set (it runs
// before the bundle), so update both together.
export type Language = 'en' | 'es' | 'pt' | 'ru' | 'zh' | 'ar' | 'fa'

export const LANGUAGES: { code: Language; tag: string; name: string; rtl?: boolean }[] = [
  { code: 'en', tag: 'en-IN', name: 'English' },
  { code: 'es', tag: 'es', name: 'Español' },
  { code: 'pt', tag: 'pt-BR', name: 'Português' },
  { code: 'ru', tag: 'ru', name: 'Русский' },
  { code: 'zh', tag: 'zh-CN', name: '中文' },
  { code: 'ar', tag: 'ar', name: 'العربية', rtl: true },
  { code: 'fa', tag: 'fa', name: 'فارسی', rtl: true },
]

export const LANGUAGE_KEY = 'marketmyna.lang'

function isLanguage(value: unknown): value is Language {
  return LANGUAGES.some((l) => l.code === value)
}

export function languageInfo(code: Language) {
  return LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0]
}

/** The saved choice, else the first browser language we offer, else English. */
export function detectLanguage(): Language {
  try {
    const saved = localStorage.getItem(LANGUAGE_KEY)
    if (isLanguage(saved)) return saved
  } catch {
    // storage unavailable - fall through to the browser languages
  }
  for (const tag of navigator.languages ?? [navigator.language]) {
    const code = tag?.toLowerCase().split('-')[0]
    if (isLanguage(code)) return code
  }
  return 'en'
}
