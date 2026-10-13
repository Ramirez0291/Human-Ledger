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
import { ledgerRegion } from '../lib/region'

interface Props {
  /** 已有草稿批次时追加 */
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

/**
 * CSV 导入（需求书 F9）。
 *
 * 选文件 → 预览（编码 / 格式识别 / 行数）→ 导入到待确认区。
 * 三井住友的两种格式自动识别；未识别的格式给出列映射编辑器。
 *
 * 每个文件各选各的入账账户：一次拖进银行明细、两张信用卡和 PayPay 很常见。
 * 默认值由后端逐文件推荐（记得你上次把同一种格式放进了哪个账户），
 * 类型对不上（银行明细选了信用卡）时就地提示。
 *
 * 微信账单一份文件跨多个账户（零钱 + 绑定的银行卡），不选文件账户，
 * 改为「支付方式 → 账户」逐项映射；对不上的默认新建，后端记住选择。
 * 币种与账本不符的文件只提示、导入时跳过。
 */
export function CsvImportForm({ batchId, onImported }: Props) {
  const { t } = useTranslation()
  const { accounts, refreshAccounts } = useLedger()

  const [files, setFiles] = useState<File[]>([])
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  // 文件名 → 入账账户
  const [fileAccounts, setFileAccounts] = useState<Record<string, number>>({})
  // 支付方式键 → 账户（'new' 表示按原文新建）
  const [methodAccounts, setMethodAccounts] = useState<Record<string, number | 'new'>>({})
  const [mapping, setMapping] = useState<ColumnMapping | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // 未识别格式时需要映射编辑器；识别出格式时映射由后端决定
  const needsMapping = useMemo(
    () => !!preview && preview.files.some((f) => f.profile === null),
    [preview],
  )
  const firstUnknown = preview?.files.find((f) => f.profile === null) ?? null

  useEffect(() => {
    if (!preview) return
    // 已经手动选过的文件保留选择；新加入的文件用推荐值
    setFileAccounts((prev) => {
      const next: Record<string, number> = {}
      for (const f of preview.files) {
        next[f.filename] =
          prev[f.filename] ?? f.suggested_account_id ?? preview.suggested_account_id ?? accounts[0]?.id
      }
      return next
    })
    setMethodAccounts((prev) => {
      const next: Record<string, number | 'new'> = {}
      for (const m of preview.payment_methods) next[m.key] = prev[m.key] ?? m.account_id ?? 'new'
      return next
    })
    if (firstUnknown?.mapping) setMapping(firstUnknown.mapping)
    else if (firstUnknown)
      setMapping({ date: 0, merchant: 1, amount: 2, has_header: true, positive_is_expense: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview])

  /**
   * 文件列表以下方的清单为准，而不是原生 file input：
   * 再次选择是追加（同名文件替换），每一项可单独移除，选完立刻清空 input，
   * 避免它显示的「N ファイル」与清单不一致。
   */
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

  // 移除只做本地过滤：预览结果按文件独立，不必再请求一次
  function removeFile(name: string) {
    const arr = files.filter((f) => f.name !== name)
    setFiles(arr)
    setPreview(
      arr.length && preview
        ? { ...preview, files: preview.files.filter((f) => f.filename !== name) }
        : null,
    )
  }

  // 跨账户的文件（微信）与币种不符的文件都不需要选文件账户
  const byName = useMemo(() => new Map(preview?.files.map((f) => [f.filename, f]) ?? []), [preview])
  const needsFileAccount = (name: string) => {
    const f = byName.get(name)
    return !f || (!f.multi_account && !f.currency_mismatch)
  }
  const ready =
    files.length > 0 && files.every((f) => !needsFileAccount(f.name) || fileAccounts[f.name] !== undefined)
  const methods = preview?.payment_methods ?? []

  async function submit() {
    if (!ready) return
    setError('')
    setBusy(true)
    try {
      const detail = await api.importCsv(
        files,
        files.map((f) => (needsFileAccount(f.name) ? fileAccounts[f.name] : 0)),
        needsMapping ? mapping : null,
        batchId,
        methods.length ? methodAccounts : null,
      )
      // 映射里选了「新建」的，后端已经建好账户：刷新列表，待确认区才显示得出账户名
      if (Object.values(methodAccounts).includes('new')) await refreshAccounts()
      onImported(detail)
      setFiles([])
      setPreview(null)
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const totalRows =
    preview?.files.reduce((n, f) => n + (f.currency_mismatch ? 0 : f.row_count), 0) ?? 0

  function kindMismatch(kind: string | null, accountId: number | undefined): boolean {
    if (!kind || accountId === undefined) return false
    const a = accounts.find((x) => x.id === accountId)
    return !!a && a.type !== kind
  }

  return (
    <div className="import-form">
      {error && <div className="alert error">{error}</div>}

      <div className="field">
        <label htmlFor="csv-files">{t('csv.files')}</label>
        <input
          id="csv-files"
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
                {f.currency_mismatch ? (
                  <span
                    className="tag warn"
                    title={t('csv.currencyMismatchHint', { currency: f.currency, ledger: ledgerRegion().currency })}
                  >
                    {t('csv.currencyMismatch', { currency: f.currency })}
                  </span>
                ) : f.multi_account ? (
                  <span className="tag">{t('csv.multiAccount')}</span>
                ) : (
                  <span className="csv-file-account">
                    <span className="muted small">→</span>
                    <select
                      aria-label={t('csv.accountFor', { name: f.filename })}
                      value={fileAccounts[f.filename] ?? ''}
                      onChange={(e) => setFileAccounts({ ...fileAccounts, [f.filename]: Number(e.target.value) })}
                    >
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                    {kindMismatch(f.account_kind, fileAccounts[f.filename]) && (
                      <span className="tag warn" title={t('csv.kindMismatchHint')}>
                        {t('csv.kindMismatch', { kind: t(`accountType.${f.account_kind}`) })}
                      </span>
                    )}
                  </span>
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

          <p className="hint">{t('csv.perFileAccountHint')}</p>

          {methods.length > 0 && (
            <div className="method-map">
              <h3>{t('csv.methodsTitle')}</h3>
              <p className="card-desc">{t('csv.methodsDesc')}</p>
              <ul>
                {methods.map((m) => (
                  <li key={m.key}>
                    <span className="method-label">{m.label}</span>
                    <span className="muted small">{t('csv.methodRows', { count: m.count })}</span>
                    <span className="muted small" aria-hidden="true">→</span>
                    <select
                      aria-label={t('csv.methodFor', { name: m.label })}
                      value={String(methodAccounts[m.key] ?? 'new')}
                      onChange={(e) =>
                        setMethodAccounts({
                          ...methodAccounts,
                          [m.key]: e.target.value === 'new' ? 'new' : Number(e.target.value),
                        })
                      }
                    >
                      <option value="new">
                        {t('csv.newAccount', { name: m.new_name, type: t(`accountType.${m.new_type}`) })}
                      </option>
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {needsMapping && firstUnknown && mapping && (
            <div className="mapping-editor">
              <p className="card-desc">{t('csv.mappingDesc')}</p>
              <div className="mapping-grid">
                {ROLES.map((role) => (
                  <div className="field" key={role}>
                    <label>{t(`csv.role.${role}`)}</label>
                    <select
                      // ROLES 只含列索引类角色，但 ColumnMapping 也有布尔字段，类型上要收窄
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
              disabled={busy || !ready || totalRows === 0}
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
