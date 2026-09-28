import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

/* Locales are auto-discovered from ./locales/*.json. */
type LocaleBundle = {
  _meta: { locale: string; nativeName: string }
  [key: string]: unknown
}

const modules = import.meta.glob<LocaleBundle>('./locales/*.json', {
  eager: true,
  import: 'default',
})

export interface LocaleInfo {
  code: string
  nativeName: string
}

const resources: Record<string, { translation: LocaleBundle }> = {}
const localeList: LocaleInfo[] = []

for (const bundle of Object.values(modules)) {
  const code = bundle._meta?.locale
  if (!code) continue
  resources[code] = { translation: bundle }
  localeList.push({ code, nativeName: bundle._meta.nativeName ?? code })
}

const PREFERRED_ORDER = ['zh-CN', 'ja', 'en']
localeList.sort((a, b) => {
  const ia = PREFERRED_ORDER.indexOf(a.code)
  const ib = PREFERRED_ORDER.indexOf(b.code)
  if (ia !== -1 && ib !== -1) return ia - ib
  if (ia !== -1) return -1
  if (ib !== -1) return 1
  return a.code.localeCompare(b.code)
})

export const SUPPORTED_LOCALES = localeList
export const LOCALE_STORAGE_KEY = 'human-ledger.locale'

/* supportedLngs needs both 'zh-CN' and 'zh' when nonExplicitSupportedLngs is on. */
const supportedLngs = Array.from(
  new Set(localeList.flatMap((l) => [l.code, l.code.split('-')[0]])),
)

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'zh-CN',
    supportedLngs,
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: LOCALE_STORAGE_KEY,
      caches: ['localStorage'],
    },
  })

export function applyLocale(code: string) {
  void i18n.changeLanguage(code)
  document.documentElement.lang = code
}

i18n.on('languageChanged', (lng) => {
  document.documentElement.lang = lng
})

export default i18n
