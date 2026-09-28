import { useTranslation } from 'react-i18next'
import { SUPPORTED_LOCALES, applyLocale } from '../i18n'

interface Props {
  onPersist?: (locale: string) => void
}

export function LanguageSwitcher({ onPersist }: Props) {
  const { i18n, t } = useTranslation()
  const current = i18n.resolvedLanguage ?? i18n.language

  return (
    <div className="lang-switch" role="group" aria-label={t('common.language')}>
      {SUPPORTED_LOCALES.map((locale) => (
        <button
          key={locale.code}
          type="button"
          aria-pressed={locale.code === current}
          onClick={() => {
            applyLocale(locale.code)
            onPersist?.(locale.code)
          }}
        >
          {locale.nativeName}
        </button>
      ))}
    </div>
  )
}
