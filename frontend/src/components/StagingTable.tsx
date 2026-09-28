import { memo, useCallback, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Account, type StagedRow, type StagedRowUpdate } from '../api/client'
import { CategoryManager } from './CategoryManager'
import { Modal } from './Modal'
import { useLedger } from '../context/LedgerContext'
import { formatJPY } from '../lib/format'
import { LazySelect, type LazyOption } from './LazySelect'

interface Props {
  batchId: number
  rows: StagedRow[]
  onChange: (rows: StagedRow[]) => void
  readOnly?: boolean
}

export function StagingTable({ batchId, rows, onChange, readOnly }: Props) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const { accounts, categories } = useLedger()

  const [showExcluded, setShowExcluded] = useState(false)
  const [busyRow, setBusyRow] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pickFor, setPickFor] = useState<StagedRow | null>(null)
  const [manageOpen, setManageOpen] = useState(false)

  const active = useMemo(() => rows.filter((r) => !r.excluded), [rows])
  const excluded = useMemo(() => rows.filter((r) => r.excluded), [rows])

  const categoryOptions = useMemo(() => {
    const build = (type: 'expense' | 'income'): LazyOption[] =>
      categories
        .filter((c) => c.type === type)
        .flatMap((c) => [
          { value: c.id, label: c.name },
          ...c.children.map((ch) => ({ value: ch.id, label: `　${ch.name}` })),
        ])
    const more: LazyOption = { value: MORE_CATEGORIES, label: t('staging.moreCategories') }
    return { expense: [...build('expense'), more], income: [...build('income'), more] }
  }, [categories, t])
  const accountOptions = useMemo<LazyOption[]>(
    () => accounts.map((a) => ({ value: a.id, label: a.name })),
    [accounts],
  )

  const summary = useMemo(() => {
    let expense = 0
    let income = 0
    let transfer = 0
    let transferCount = 0
    for (const r of active) {
      if (!r.is_selected || r.amount === null) continue
      if (r.transfer_hint) {
        transfer += r.amount
        transferCount += 1
      } else if (r.direction === 'income') income += r.amount
      else expense += r.amount
    }
    return { expense, income, transfer, transferCount }
  }, [active])
  const selectedCount = active.filter((r) => r.is_selected).length

  // Read latest rows via ref so callbacks stay stable for memo.
  const rowsRef = useRef(rows)
  rowsRef.current = rows
  const replace = useCallback(
    (updated: StagedRow | StagedRow[]) => {
      const list = Array.isArray(updated) ? updated : [updated]
      const byId = new Map(list.map((r) => [r.id, r]))
      onChange(rowsRef.current.map((r) => byId.get(r.id) ?? r))
    },
    [onChange],
  )

  const patch = useCallback(
    async (row: StagedRow, body: StagedRowUpdate) => {
      setBusyRow(row.id)
      try {
        const res = await api.updateStagedRow(batchId, row.id, body)
        replace([res.row, ...res.affected])
        if (res.affected.length > 0) {
          setNotice(t('staging.appliedToSimilar', { count: res.affected.length }))
          window.setTimeout(() => setNotice(null), 4000)
        }
      } finally {
        setBusyRow(null)
      }
    },
    [batchId, replace, t],
  )

  const localEdit = useCallback((row: StagedRow) => replace(row), [replace])
  const openPicker = useCallback((row: StagedRow) => setPickFor(row), [])

  async function setAll(selected: boolean) {
    const ids = active.map((r) => r.id)
    replace(await api.bulkUpdate(batchId, { row_ids: ids, is_selected: selected }))
  }

  const expand = useCallback(
    async (row: StagedRow) => {
      await api.expandMerged(batchId, row.id)
      const detail = await api.importBatch(batchId)
      onChange(detail.rows)
    },
    [batchId, onChange],
  )

  async function restore(row: StagedRow) {
    replace(await api.restoreExcluded(batchId, row.id))
  }

  function excludeReason(row: StagedRow): string {
    const key = `staging.exclude.${row.exclude_reason ?? 'unknown'}`
    return t(key, row.exclude_reason ?? '')
  }

  return (
    <div className="staging">
      <div className="staging-toolbar">
        <span className="muted staging-summary">
          {t('staging.summaryCount', { selected: selectedCount, total: active.length })}
          <span className="expense">−{formatJPY(summary.expense, locale)}</span>
          {summary.income > 0 && <span className="income">+{formatJPY(summary.income, locale)}</span>}
          {summary.transferCount > 0 && (
            <span title={t('staging.summaryTransferHint')}>
              {t('staging.summaryTransfer', {
                count: summary.transferCount,
                amount: formatJPY(summary.transfer, locale),
              })}
            </span>
          )}
        </span>
        {!readOnly && (
          <span className="staging-bulk">
            <button className="btn-ghost" onClick={() => setManageOpen(true)}>
              {t('staging.manageCategories')}
            </button>
            <button className="btn-ghost" onClick={() => void setAll(true)}>
              {t('staging.selectAll')}
            </button>
            <button className="btn-ghost" onClick={() => void setAll(false)}>
              {t('staging.selectNone')}
            </button>
          </span>
        )}
      </div>

      {notice && <div className="staging-notice">{notice}</div>}

      <div className="staging-list">
        {active.map((row) => (
          <StagingRow
            key={row.id}
            row={row}
            busy={busyRow === row.id}
            readOnly={!!readOnly}
            locale={locale}
            accounts={accounts}
            accountOptions={accountOptions}
            categoryOptions={row.direction === 'income' ? categoryOptions.income : categoryOptions.expense}
            onPatch={patch}
            onLocalEdit={localEdit}
            onExpand={expand}
            onOpenPicker={openPicker}
          />
        ))}

        {active.length === 0 && <p className="muted staging-empty">{t('staging.empty')}</p>}
      </div>

      {excluded.length > 0 && (
        <div className="staging-excluded">
          <button className="btn-ghost" onClick={() => setShowExcluded((v) => !v)}>
            {showExcluded ? '▾' : '▸'} {t('staging.excludedTitle', { count: excluded.length })}
          </button>
          {showExcluded && (
            <ul>
              {excluded.map((row) => (
                <li key={row.id}>
                  <span className="tag">{excludeReason(row)}</span>
                  <span className="staging-excluded-text">
                    {row.merchant_raw || row.raw_text?.split('\n')[0] || '—'}
                  </span>
                  {row.amount !== null && (
                    <span className="mono muted">{formatJPY(row.amount, locale)}</span>
                  )}
                  {!readOnly && row.exclude_reason !== 'merged' && (
                    <button className="btn-ghost" onClick={() => void restore(row)}>
                      {t('staging.restore')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Modal
        open={pickFor !== null}
        title={t('staging.pickCategoryFor', { merchant: pickFor?.merchant_raw ?? '' })}
        onClose={() => setPickFor(null)}
        size="wide"
      >
        {pickFor && (
          <CategoryManager
            type={pickFor.direction === 'income' ? 'income' : 'expense'}
            onPick={(c) => {
              const row = pickFor
              setPickFor(null)
              void patch(row, { category_id: c.id })
            }}
          />
        )}
      </Modal>

      <Modal
        open={manageOpen}
        title={t('category.title')}
        onClose={() => setManageOpen(false)}
        size="wide"
      >
        <CategoryManager />
      </Modal>
    </div>
  )
}

const MORE_CATEGORIES = '__more'

// --------------------------------------------------------------------------
// --------------------------------------------------------------------------

interface RowProps {
  row: StagedRow
  busy: boolean
  readOnly: boolean
  locale: string
  accounts: Account[]
  accountOptions: LazyOption[]
  categoryOptions: LazyOption[]
  onPatch: (row: StagedRow, body: StagedRowUpdate) => Promise<void>
  onLocalEdit: (row: StagedRow) => void
  onExpand: (row: StagedRow) => Promise<void>
  onOpenPicker: (row: StagedRow) => void
}

const StagingRow = memo(function StagingRow({
  row,
  busy,
  readOnly,
  locale,
  accounts,
  accountOptions,
  categoryOptions,
  onPatch,
  onLocalEdit,
  onExpand,
  onOpenPicker,
}: RowProps) {
  const { t } = useTranslation()
  const dup = dupLabel(row, t)
  const complete = row.date && row.amount !== null && row.merchant_raw

  const counterpartOptions = useMemo<LazyOption[]>(
    () =>
      accounts
        .filter((a) => a.id !== row.account_id)
        .map((a) => ({ value: a.id, label: `${row.direction === 'income' ? '←' : '→'} ${a.name}` })),
    [accounts, row.account_id, row.direction],
  )

  return (
    <div
      className={`staging-row ${dup?.cls ?? ''} ${row.is_selected ? '' : 'unselected'} ${busy ? 'busy' : ''}`}
    >
      <label className="staging-check">
        <input
          type="checkbox"
          checked={row.is_selected}
          disabled={readOnly || !complete}
          onChange={(e) => void onPatch(row, { is_selected: e.target.checked })}
        />
      </label>

      <div className="staging-main">
        <div className="staging-line1">
          <input
            className="staging-merchant"
            type="text"
            value={row.merchant_raw}
            disabled={readOnly}
            onChange={(e) => onLocalEdit({ ...row, merchant_raw: e.target.value })}
            onBlur={(e) => void onPatch(row, { merchant_raw: e.target.value })}
          />
          <span className={`staging-amount mono ${row.direction ?? ''}`}>
            {row.direction === 'income' ? '+' : '−'}
            {row.amount !== null ? formatJPY(row.amount, locale) : '?'}
          </span>
        </div>

        <div className="staging-line2">
          <input
            type="date"
            className={`staging-date ${row.date_inferred ? 'inferred' : ''}`}
            value={row.date ?? ''}
            disabled={readOnly}
            title={row.date_inferred ? t('staging.dateInferred') : undefined}
            onChange={(e) => void onPatch(row, { date: e.target.value })}
          />
          {row.date_inferred && <span className="tag">{t('staging.dateInferred')}</span>}

          <LazySelect
            className="staging-select"
            value={row.category_id ?? ''}
            options={categoryOptions}
            disabled={readOnly}
            placeholder={t('form.noCategory')}
            onChange={(v) => {
              if (v === MORE_CATEGORIES) onOpenPicker(row)
              else void onPatch(row, v ? { category_id: Number(v) } : { clear_category: true })
            }}
          />
          {sourceBadge(row, t) && <span className="tag">{sourceBadge(row, t)}</span>}

          <LazySelect
            className="staging-select"
            value={row.account_id ?? ''}
            options={accountOptions}
            disabled={readOnly}
            placeholder={t('form.account')}
            onChange={(v) => v && void onPatch(row, { account_id: Number(v) })}
          />

          {row.installment_total && (
            <span className="tag">
              {t('txn.installmentTag', {
                current: row.installment_current ?? '?',
                total: row.installment_total,
              })}
              {row.memo === 'installment_estimated' && ` · ${t('staging.estimated')}`}
            </span>
          )}
          {row.balance_after !== null && (
            <span className="tag mono">
              {t('staging.balanceAfter')} {formatJPY(row.balance_after, locale)}
            </span>
          )}
        </div>

        {row.transfer_hint && (
          <div className="staging-transfer">
            <span>{t('staging.transferHint')}</span>
            <LazySelect
              className="staging-select"
              value={row.counterpart_account_id ?? ''}
              options={counterpartOptions}
              disabled={readOnly}
              placeholder={t('staging.transferNotTransfer')}
              onChange={(v) =>
                void onPatch(row, v ? { counterpart_account_id: Number(v) } : { clear_counterpart: true })
              }
            />
          </div>
        )}

        {dup && (
          <div className={`staging-dup ${dup.cls}`}>
            <strong>{dup.text}</strong>
            <span>{dupReason(row, t)}</span>
            {row.dup_status === 'merged' && !readOnly && (
              <button className="btn-ghost" onClick={() => void onExpand(row)}>
                {t('staging.expand')}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
})

type T = (key: string, opts?: Record<string, unknown>) => string

function dupLabel(row: StagedRow, t: T): { text: string; cls: string } | null {
  if (row.dup_status === 'duplicate') return { text: t('staging.dupDuplicate'), cls: 'dup-red' }
  if (row.dup_status === 'maybe') return { text: t('staging.dupMaybe'), cls: 'dup-yellow' }
  if (row.dup_status === 'merged')
    return { text: t('staging.dupMerged', { count: row.merged_count }), cls: 'dup-blue' }
  return null
}

function dupReason(row: StagedRow, t: T): string {
  const r = row.dup_reason ?? ''
  if (r.startsWith('exact:')) return t('staging.reasonExact', { what: r.slice(6) })
  if (r.startsWith('transfer_leg:')) return t('staging.reasonTransferLeg', { what: r.slice(13) })
  if (r.startsWith('fuzzy:')) {
    const [, score, ...rest] = r.split(':')
    return t('staging.reasonFuzzy', { what: rest.join(':'), score: Math.round(Number(score) * 100) })
  }
  if (r.startsWith('merged:')) return t('staging.reasonMerged', { count: Number(r.slice(7)) })
  if (r.startsWith('same_in_batch:')) return t('staging.reasonSameInBatch', { count: Number(r.slice(14)) })
  if (r === 'expanded') return t('staging.reasonExpanded')
  return r
}

function sourceBadge(row: StagedRow, t: T): string | null {
  if (!row.category_id) return null
  if (row.category_source === 'rule') return t('staging.srcRule')
  if (row.category_source === 'memory') return t('staging.srcMemory')
  if (row.category_source === 'dictionary') return t('staging.srcDictionary')
  return null
}
