import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

/**
 * 语言文件自动发现。
 *
 * 新增一种语言只需在 src/i18n/locales/ 下放一个 <locale>.json，
 * 内含 _meta.locale 与 _meta.nativeName，无需修改任何代码。
 * （后端侧还需在 seed.py 的 SUPPORTED_LOCALES 与类目名称中补上对应语言。）
 */
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

// 固定展示顺序：中文 → 日语 → 英语 → 其余按字母序
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
export const LOCALE_STORAGE_KEY = 'renlei.locale'

/**
 * supportedLngs 必须同时包含完整语言码与其语言部分（zh-CN 与 zh）。
 *
 * 原因：开启 nonExplicitSupportedLngs 后，i18next 的 isSupportedCode() 会先把
 * 语言码截断为语言部分再去 supportedLngs 里查。若只登记 'zh-CN'，那么查 'zh-CN'
 * 时它实际比对的是 'zh'，匹配失败 → 'zh-CN' 被判为不支持并从解析链中剔除，
 * 连 fallbackLng 也一同被剔除，界面会直接显示原始 key。
 * 'ja' / 'en' 不含连字符，截断后仍是自身，因此不会暴露此问题。
 *
 * 同时包含两者还带来一个好处：浏览器报 zh-TW / zh-HK 时能正确回落到 zh-CN。
 */
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
    // 使 zh-TW / en-GB 之类的变体能回落到已有语言，而不是直接落到 fallback
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: LOCALE_STORAGE_KEY,
      caches: ['localStorage'],
    },
  })

/** 切换语言并同步 <html lang>，便于浏览器选择正确的字体与断行规则。 */
export function applyLocale(code: string) {
  void i18n.changeLanguage(code)
  document.documentElement.lang = code
}

i18n.on('languageChanged', (lng) => {
  document.documentElement.lang = lng
})

export default i18n
