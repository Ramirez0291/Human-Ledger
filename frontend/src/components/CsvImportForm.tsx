import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ApiError,
  api,
  type BatchDetail,
  type ColumnMapping,
  type CsvPreview,
} from '../api/client'
import { useLedger } from '../context/LedgerContext'

interface Props {
  batchId: number | null
  onImported: (detail: BatchDetail) => void
}

const ROLES: (keyof ColumnMapping)[] = [
  'date',
  'merchant',
  'amount',
  'withdrawal',
  'deposit',
  'balance',
  'memo',
]

export function CsvImportForm({ batchId, onImported }: Props) {
  const { t } = useTranslation()
  const { accounts } = useLedger()

  const [files, setFiles] = useState<File[]>([])
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  const [accountId, setAccountId] = useState<number | ''>('')
  const [mapping, setMapping] = useState<ColumnMapping | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const needsMapping = useMemo(
    () => !!preview && preview.files.some((f) => f.profile === null),
    [preview],
  )
  const firstUnknown = preview?.files.find((f) => f.profile === null) ?? null

  useEffect(() => {
    if (!preview) return
    if (preview.suggested_account_id) setAccountId(preview.suggested_account_id)
    else if (accountId === '' && accounts.length) setAccountId(accounts[0].id)
    if (firstUnknown?.mapping) setMapping(firstUnknown.mapping)
    else if (firstUnknown)
      setMapping({ date: 0, merchant: 1, amount: 2, has_header: true, positive_is_expense: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview])

  async function pick(list: FileList | null) {
    const added = list ? Array.from(list) : []
    if (inputRef.current) inputRef.current.value = ''
    if (!added.length) return
    const names = new Set(added.map((f) => f.name))
    const arr = [...files.filter((f) => !names.has(f.name)), ...added]
    setFiles(arr)
    setError('')
    setBusy(true)
    try {
      setPreview(await api.csvPreview(arr))
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  function removeFile(name: string) {
    const arr = files.filter((f) => f.name !== name)
    setFiles(arr)
    setPreview(
      arr.length && preview
        ? { ...preview, files: preview.files.filter((f) => f.filename !== name) }
        : null,
    )
  }

  async function submit() {
    if (!files.length || accountId === '') return
    setError('')
    setBusy(true)
    try {
      const detail = await api.importCsv(files, accountId, needsMapping ? mapping : null, batchId)
      onImported(detail)
      setFiles([])
      setPreview(null)
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const totalRows = preview?.files.reduce((n, f) => n + f.row_count, 0) ?? 0

  return (
    <div className="import-form">
      {error && <div className="alert error">{error}</div>}

      <div className="field">
        <label htmlFor="csv-files">{t('csv.files')}</label>
        <input
          id="csv-files"
          ref={inputRef}
          type="file"
          accept=".csv,text/csv,text/plain"
          multiple
          onChange={(e) => void pick(e.target.files)}
        />
        <span className="hint">{t('csv.filesHint')}</span>
      </div>

      {preview && (
        <>
          <ul className="csv-file-list">
            {preview.files.map((f) => (
              <li key={f.filename} className={f.profile ? '' : 'unknown'}>
                <span className="csv-filename">{f.filename}</span>
                <span className="tag">{f.encoding}</span>
                <span className={`tag ${f.profile ? 'ok' : 'warn'}`}>
                  {f.profile_name ?? t('csv.unknownFormat')}
                </span>
                <span className="muted">{t('csv.rows', { count: f.row_count })}</span>
                {f.statement_month && (
                  <span className="muted">{t('csv.statement', { month: f.statement_month })}</span>
                )}
                {f.previously_imported && (
                  <span className="tag warn">{t('csv.previouslyImported')}</span>
                )}
                <button
                  type="button"
                  className="btn-ghost csv-remove"
                  aria-label={t('csv.removeFile', { name: f.filename })}
                  title={t('csv.removeFile', { name: f.filename })}
                  disabled={busy}
                  onClick={() => removeFile(f.filename)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>

          <div className="field">
            <label htmlFor="csv-account">{t('form.account')}</label>
            <select
              id="csv-account"
              value={accountId}
              onChange={(e) => setAccountId(Number(e.target.value))}
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            {preview.suggested_account_id && (
              <span className="hint">{t('csv.accountSuggested')}</span>
            )}
          </div>

          {needsMapping && firstUnknown && mapping && (
            <div className="mapping-editor">
              <p className="card-desc">{t('csv.mappingDesc')}</p>
              <div className="mapping-grid">
                {ROLES.map((role) => (
                  <div className="field" key={role}>
                    <label>{t(`csv.role.${role}`)}</label>
                    <select
                      value={typeof mapping[role] === 'number' ? (mapping[role] as number) : ''}
                      onChange={(e) =>
                        setMapping({
                          ...mapping,
                          [role]: e.target.value === '' ? null : Number(e.target.value),
                        })
                      }
                    >
                      <option value="">—</option>
                      {(firstUnknown.header.length
                        ? firstUnknown.header
                        : firstUnknown.sample[0] ?? []
                      ).map((h, i) => (
                        <option key={i} value={i}>
                          {i + 1}: {h || `(${t('csv.emptyHeader')})`}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
              <div className="mapping-options">
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={mapping.has_header ?? true}
                    onChange={(e) => setMapping({ ...mapping, has_header: e.target.checked })}
                  />
                  <span>{t('csv.hasHeader')}</span>
                </label>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={mapping.positive_is_expense ?? true}
                    onChange={(e) =>
                      setMapping({ ...mapping, positive_is_expense: e.target.checked })
                    }
                  />
                  <span>{t('csv.positiveIsExpense')}</span>
                </label>
              </div>
              <div className="csv-sample">
                <table>
                  <tbody>
                    {firstUnknown.sample.map((row, i) => (
                      <tr key={i}>
                        {row.map((c, j) => (
                          <td key={j}>{c}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="form-actions">
            <button
              className="btn-primary"
              disabled={busy || accountId === '' || totalRows === 0}
              onClick={() => void submit()}
            >
              {busy ? t('import.parsing') : t('csv.import', { count: totalRows })}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
