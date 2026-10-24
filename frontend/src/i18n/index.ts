import i18n, { type BackendModule } from 'i18next'
import { initReactI18next } from 'react-i18next'
import { detectLanguage, LANGUAGE_KEY, languageInfo, type Language } from './languages'

// Translations live in src/i18n/locales/<language>/<namespace>.json, one
// namespace per area of the app (common, app, markets). English ships in the
// main bundle and is the fallback for any missing key; the other languages
// load on demand, one namespace at a time, when a component asks for it.
const english = import.meta.glob<Record<string, unknown>>('./locales/en/*.json', { eager: true, import: 'default' })
const others = import.meta.glob<Record<string, unknown>>(['./locales/*/*.json', '!./locales/en/*.json'], { import: 'default' })

const nsOf = (path: string) => path.split('/').pop()!.replace('.json', '')

const en = Object.fromEntries(Object.entries(english).map(([path, data]) => [nsOf(path), data]))

const lazyLocales: BackendModule = {
  type: 'backend',
  init() {},
  read(language, namespace, done) {
    const load = others[`./locales/${language}/${namespace}.json`]
    if (!load) return done(null, {})
    load().then(
      (data) => done(null, data),
      (error: Error) => done(error, null),
    )
  },
}

/** Put the language on <html> (lang for fonts, screen readers and search; dir for right-to-left layout). */
function applyToDocument(code: Language) {
  const info = languageInfo(code)
  document.documentElement.lang = info.tag
  document.documentElement.dir = info.rtl ? 'rtl' : 'ltr'
}

const initial = detectLanguage()
applyToDocument(initial)

i18n
  .use(lazyLocales)
  .use(initReactI18next)
  .init({
    lng: initial,
    fallbackLng: 'en',
    resources: { en },
    partialBundledLanguages: true,
    // Only the shared strings (site and app shell) load up front; each page's namespace loads when the page asks for it.
    ns: ['common', 'app'],
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    returnNull: false,
  })

i18n.on('languageChanged', (code) => applyToDocument(code as Language))

export function setLanguage(code: Language) {
  try {
    localStorage.setItem(LANGUAGE_KEY, code)
  } catch {
    // storage unavailable - the choice lasts for this page only
  }
  void i18n.changeLanguage(code)
}

export default i18n
