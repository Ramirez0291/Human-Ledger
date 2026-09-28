import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type OcrProviders, type SystemInfo } from '../api/client'
import { CategoryManager } from '../components/CategoryManager'
import { RulesPanel } from '../components/RulesPanel'

export function SettingsPage() {
  const { t } = useTranslation()

  const [providers, setProviders] = useState<OcrProviders | null>(null)
  const [system, setSystem] = useState<SystemInfo | null>(null)

  useEffect(() => {
    void api.ocrProviders().then(setProviders).catch(() => undefined)
    void api.system().then(setSystem).catch(() => undefined)
  }, [])

  const providerLabel: Record<string, string> = {
    none: t('ocr.providerNone'),
    local: t('ocr.providerLocal'),
    cloud_llm: t('ocr.providerCloudLlm'),
  }

  return (
    <>
      <div className="page-head">
        <h1>{t('nav.settings')}</h1>
      </div>

      <div className="card">
        <div className="card-header">
          <h2>{t('category.title')}</h2>
        </div>
        <p className="card-desc">{t('category.desc')}</p>
        <CategoryManager />
      </div>

      <RulesPanel />

      <div className="card">
        <div className="card-header">
          <h2>{t('ocr.title')}</h2>
        </div>
        <p className="card-desc">
          {t('ocr.desc')}
          {providers && ` ${t(providers.note_key)}`}
        </p>
        <div style={{ marginTop: 12 }}>
          {providers?.providers.map((p) => (
            <div className="provider-row" key={p.key}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="provider-name">
                  {providerLabel[p.key] ?? p.key}{' '}
                  <span className="mono muted" style={{ fontSize: '0.75rem' }}>
                    {p.key}
                  </span>
                </div>
                <div className="provider-reason">{t(p.reason_key)}</div>
              </div>
              {p.active && <span className="badge done">{t('ocr.active')}</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h2>{t('backup.title')}</h2>
        </div>
        <p className="card-desc">{t('backup.desc')}</p>
        <div className="backup-actions">
          <a className="btn-primary link-btn-inline" href={api.backupUrl} download>
            {t('backup.download')}
          </a>
          <a className="btn-ghost link-btn-inline" href={api.exportUrl()} download>
            {t('backup.exportAll')}
          </a>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          {t('backup.restoreHint')} <code>python scripts/restore_backup.py &lt;zip&gt;</code>
        </p>
      </div>

      {system && (
        <div className="card">
          <div className="card-header">
            <h2>{t('settings.about')}</h2>
          </div>
          <dl className="kv">
            <div>
              <dt>{t('settings.database')}</dt>
              <dd className="mono">
                {system.database} · {system.table_count} tables
              </dd>
            </div>
            <div>
              <dt>{t('settings.migration')}</dt>
              <dd className="mono">{system.migration_revision ?? '—'}</dd>
            </div>
            <div>
              <dt>{t('settings.timezone')}</dt>
              <dd className="mono">{system.timezone}</dd>
            </div>
          </dl>
        </div>
      )}

    </>
  )
}
