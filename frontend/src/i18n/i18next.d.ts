// Type-checks every t('...') key against the English files: a typo or a key
// missing from English fails the build. Add each new namespace here.
import 'i18next'
import type common from './locales/en/common.json'
import type app from './locales/en/app.json'
import type markets from './locales/en/markets.json'

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'common'
    resources: {
      common: typeof common
      app: typeof app
      markets: typeof markets
    }
  }
}
