import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  api,
  type BatchDetail,
  type ConfirmResult,
  type ImportBatch,
  type StagedRow,
} from '../api/client'
import { CsvImportForm } from '../components/CsvImportForm'
import { ImportHistory } from '../components/ImportHistory'
import { Modal } from '../components/Modal'
import { StagingTable } from '../components/StagingTable'
import { useLedger } from '../context/LedgerContext'
import { currentYearMonth, formatJPY } from '../lib/format'

export function ImportPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const { accounts, refreshAccounts } = useLedger()
  const navigate = useNavigate()
  const params = useParams<{ batchId?: string }>()

  const [source, setSource] = useState<'csv' | 'text'>('csv')
  const [accountId, setAccountId] = useState<number | ''>('')
  const [text, setText] = useState('')
  const [statementMonth, setStatementMonth] = useState('')
  const [useStatementMonth, setUseStatementMonth] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState('')

  const [detail, setDetail] = useState<BatchDetail | null>(null)
  const onRowsChange = useCallback(
    (rows: StagedRow[]) => setDetail((d) => (d ? { ...d, rows } : d)),
    [],
  )
  const [drafts, setDrafts] = useState<ImportBatch[]>([])
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState<ConfirmResult | null>(null)

  useEffect(() => {
    if (accountId === '' && accounts.length) setAccountId(accounts[0].id)
  }, [accounts, accountId])

  const loadDrafts = useCallback(async () => {
    setDrafts(await api.importBatches('draft'))
  }, [])

  useEffect(() => {
    void loadDrafts()
  }, [loadDrafts])

  useEffect(() => {
    if (!params.batchId) return
    const id = Number(params.batchId)
    if (!id || detail?.batch.id === id) return
    void api.importBatch(id).then(setDetail).catch(() => navigate('/import'))
  }, [params.batchId, detail?.batch.id, navigate])

  async function parse() {
    if (accountId === '' || !text.trim()) return
    setError('')
    setParsing(true)
    try {
      const d = await api.importText({
        account_id: accountId,
        text,
        statement_month: useStatementMonth && statementMonth ? statementMonth : null,
        batch_id: detail?.batch.status === 'draft' ? detail.batch.id : null,
      })
      setDetail(d)
      setText('')
      navigate(`/import/${d.batch.id}`, { replace: true })
      await loadDrafts()
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setParsing(false)
    }
  }

  async function confirm() {
    if (!detail) return
    setConfirming(true)
    try {
      const r = await api.confirmBatch(detail.batch.id)
      setResult(r)
      setDetail(await api.importBatch(detail.batch.id))
      await Promise.all([loadDrafts(), refreshAccounts()])
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setConfirming(false)
    }
  }

  async function discard() {
    if (!detail || !window.confirm(t('import.confirmDiscard'))) return
    await api.discardBatch(detail.batch.id)
    setDetail(null)
    navigate('/import', { replace: true })
    await loadDrafts()
  }

  function startNew() {
    setDetail(null)
    setResult(null)
    navigate('/import', { replace: true })
  }

  const isDraft = detail?.batch.status === 'draft'
  const selectable = detail?.rows.filter((r) => !r.excluded && r.is_selected).length ?? 0

  return (
    <>
      <div className="page-head">
        <h1>{t('nav.import')}</h1>
        {detail && (
          <div className="page-actions">
            <button className="btn-ghost" onClick={startNew}>
              {t('import.startNew')}
            </button>
          </div>
        )}
      </div>

      {accounts.length === 0 && (
        <div className="empty-state card">
          <p className="card-desc">{t('account.emptyDesc')}</p>
        </div>
      )}

      {accounts.length > 0 && (!detail || isDraft) && (
        <div className="card">
          <div className="card-header import-head">
            <h2>{detail ? t('import.appendTitle') : t('import.sourceTitle')}</h2>
            <div className="segmented source-toggle" role="group">
              <button type="button" aria-pressed={source === 'csv'} onClick={() => setSource('csv')}>
                {t('import.sourceCsv')}
              </button>
              <button type="button" aria-pressed={source === 'text'} onClick={() => setSource('text')}>
                {t('import.sourceText')}
              </button>
            </div>
          </div>

          {source === 'csv' ? (
            <>
              <p className="card-desc">{t('csv.desc')}</p>
              <CsvImportForm
                batchId={detail?.batch.status === 'draft' ? detail.batch.id : null}
                onImported={async (d) => {
                  setDetail(d)
                  navigate(`/import/${d.batch.id}`, { replace: true })
                  await loadDrafts()
                }}
              />
            </>
          ) : (
            <>
              <p className="card-desc">{t('import.pasteDesc')}</p>

              {error && (
                <div className="alert error" style={{ marginTop: 12 }}>
                  {error}
                </div>
              )}

              <div className="import-form">
                <div className="form-row">
                  <div className="field">
                    <label htmlFor="imp-account">{t('form.account')}</label>
                    <select
                      id="imp-account"
                      value={accountId}
                      onChange={(e) => setAccountId(Number(e.target.value))}
                    >
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label className="checkbox-row" style={{ marginBottom: 6 }}>
                      <input
                        type="checkbox"
                        checked={useStatementMonth}
                        onChange={(e) => {
                          setUseStatementMonth(e.target.checked)
                          if (e.target.checked && !statementMonth) setStatementMonth(currentYearMonth())
                        }}
                      />
                      <span>{t('import.statementMonth')}</span>
                    </label>
                    <input
                      type="month"
                      value={statementMonth}
                      disabled={!useStatementMonth}
                      onChange={(e) => setStatementMonth(e.target.value)}
                    />
                    <span className="hint">{t('import.statementMonthHint')}</span>
                  </div>
                </div>

                <div className="field">
                  <label htmlFor="imp-text">{t('import.text')}</label>
                  <textarea
                    id="imp-text"
                    rows={10}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder={t('import.textPlaceholder')}
                    spellCheck={false}
                  />
                </div>

                <div className="form-actions">
                  <button
                    className="btn-primary"
                    disabled={parsing || !text.trim() || accountId === ''}
                    onClick={() => void parse()}
                  >
                    {parsing ? t('import.parsing') : t('import.parse')}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {!detail && drafts.length > 0 && (
        <div className="card">
          <div className="card-header">
            <h2>{t('import.draftsTitle')}</h2>
          </div>
          <ul className="draft-list">
            {drafts.map((b) => (
              <li key={b.id}>
                <span>
                  #{b.id} · {new Date(b.created_at).toLocaleString(locale)}
                </span>
                <span className="muted">
                  {t('import.draftMeta', { selected: b.selected_rows, total: b.total_rows })}
                </span>
                <button className="btn-ghost" onClick={() => navigate(`/import/${b.id}`)}>
                  {t('import.resume')}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!detail && <ImportHistory onChanged={refreshAccounts} />}

      {detail && (
        <div className="card">
          <div className="card-header staging-head">
            <h2>
              {t('staging.title')} <span className="muted mono">#{detail.batch.id}</span>
            </h2>
            {detail.batch.status === 'confirmed' && (
              <span className="badge done">{t('import.confirmed')}</span>
            )}
            {detail.batch.status === 'reverted' && <span className="badge">{t('history.reverted')}</span>}
          </div>

          {detail.previously_imported && (
            <div className="alert warn" style={{ marginTop: 10 }}>
              {t('import.previouslyImported')}
            </div>
          )}
          {detail.detected_balance !== null && (
            <p className="hint" style={{ marginTop: 8 }}>
              {t('import.detectedBalance', { amount: formatJPY(detail.detected_balance, locale) })}
            </p>
          )}
          {detail.warnings
            .filter((w) => w.startsWith('rerouted|') || w.startsWith('account_mismatch|'))
            .map((w) => {
              const [kind, file, profile, account] = w.split('|')
              return (
                <div key={w} className={`alert ${kind === 'rerouted' ? 'ok' : 'warn'}`} style={{ marginTop: 10 }}>
                  {t(kind === 'rerouted' ? 'import.rerouted' : 'import.accountMismatch', { file, profile, account })}
                </div>
              )
            })}
          {detail.warnings.some((w) => w.startsWith('installment_estimated')) && (
            <p className="hint">{t('import.installmentEstimatedWarn')}</p>
          )}

          <StagingTable
            batchId={detail.batch.id}
            rows={detail.rows}
            onChange={onRowsChange}
            readOnly={!isDraft}
          />

          {isDraft && (
            <div className="form-actions" style={{ marginTop: 16 }}>
              <button className="btn-ghost danger form-delete" onClick={() => void discard()}>
                {t('import.discard')}
              </button>
              <button
                className="btn-primary"
                disabled={confirming || selectable === 0}
                onClick={() => void confirm()}
              >
                {confirming
                  ? t('import.confirming')
                  : t('import.confirmN', { count: selectable })}
              </button>
            </div>
          )}
        </div>
      )}

      <Modal open={result !== null} title={t('import.resultTitle')} onClose={() => setResult(null)}>
        {result && (
          <div className="stack-sm">
            <dl className="kv">
              <div>
                <dt>{t('import.resultImported')}</dt>
                <dd className="mono">{result.imported}</dd>
              </div>
              {result.transfers > 0 && (
                <div>
                  <dt>{t('import.resultTransfers')}</dt>
                  <dd className="mono">{result.transfers}</dd>
                </div>
              )}
              {result.skipped_unselected > 0 && (
                <div>
                  <dt>{t('import.resultSkippedUnselected')}</dt>
                  <dd className="mono">{result.skipped_unselected}</dd>
                </div>
              )}
              {result.skipped_duplicate > 0 && (
                <div>
                  <dt>{t('import.resultSkippedDuplicate')}</dt>
                  <dd className="mono">{result.skipped_duplicate}</dd>
                </div>
              )}
              {result.skipped_excluded > 0 && (
                <div>
                  <dt>{t('import.resultSkippedExcluded')}</dt>
                  <dd className="mono">{result.skipped_excluded}</dd>
                </div>
              )}
            </dl>

            {result.reconcile && (
              <div className={`alert ${result.reconcile.diff === 0 ? 'ok' : 'warn'}`}>
                {result.reconcile.diff === 0
                  ? t('import.reconcileOk', {
                      account: result.reconcile.account_name,
                      amount: formatJPY(result.reconcile.actual_balance, locale),
                    })
                  : t('import.reconcileDiff', {
                      account: result.reconcile.account_name,
                      amount: formatJPY(result.reconcile.diff, locale),
                    })}
              </div>
            )}

            <div className="form-actions">
              <button className="btn-ghost" onClick={() => setResult(null)}>
                {t('common.close')}
              </button>
              <button
                className="btn-primary"
                onClick={() => {
                  setResult(null)
                  navigate('/transactions')
                }}
              >
                {t('import.viewTransactions')}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </>
  )
}
