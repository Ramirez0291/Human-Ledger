import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { api, type Transaction, type TransactionFilters } from '../api/client'
import { Icon } from '../components/Icon'
import { Modal } from '../components/Modal'
import { TransactionForm } from '../components/TransactionForm'
import { TransferForm } from '../components/TransferForm'
import { useLedger } from '../context/LedgerContext'
import { currentYearMonth, formatDateShort, formatJPY, formatWeekday, monthRange, shiftYearMonth, formatYearMonth } from '../lib/format'

const PAGE_SIZE = 50

export function TransactionsPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const { accounts, categories, refreshAccounts } = useLedger()

  const [params] = useSearchParams()
  const [ym, setYm] = useState(params.get('ym') ?? currentYearMonth())
  const [accountId, setAccountId] = useState<number | ''>(
    params.get('account_id') ? Number(params.get('account_id')) : '',
  )
  const [categoryId, setCategoryId] = useState<number | ''>(
    params.get('category_id') ? Number(params.get('category_id')) : '',
  )
  const [query, setQuery] = useState(params.get('q') ?? '')
  const [showTrash, setShowTrash] = useState(false)
  const [page, setPage] = useState(1)

  const [data, setData] = useState<{
    items: Transaction[]
    total: number
    sum_income: number
    sum_expense: number
  } | null>(null)
  const [editing, setEditing] = useState<Transaction | null>(null)
  const [dialog, setDialog] = useState<'none' | 'txn' | 'transfer'>('none')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const { from, to } = monthRange(ym)
    const filters: TransactionFilters = {
      date_from: from,
      date_to: to,
      page,
      page_size: PAGE_SIZE,
      include_deleted: showTrash,
    }
    if (accountId !== '') filters.account_id = accountId
    if (categoryId !== '') filters.category_id = categoryId
    if (query.trim()) filters.q = query.trim()

    try {
      setData(await api.transactions(filters))
    } finally {
      setLoading(false)
    }
  }, [ym, accountId, categoryId, query, page, showTrash])

  useEffect(() => {
    const timer = setTimeout(() => void load(), query ? 300 : 0)
    return () => clearTimeout(timer)
  }, [load, query])

  useEffect(() => {
    setPage(1)
  }, [ym, accountId, categoryId, query, showTrash])

  async function refresh() {
    setDialog('none')
    setEditing(null)
    await Promise.all([load(), refreshAccounts()])
  }

  async function remove(txn: Transaction) {
    const msg = txn.transfer_group_id ? t('txn.confirmDeleteTransfer') : t('txn.confirmDelete')
    if (!window.confirm(msg)) return
    await api.deleteTransaction(txn.id)
    await refresh()
  }

  async function restore(txn: Transaction) {
    await api.restoreTransaction(txn.id)
    await refresh()
  }

  const grouped = useMemo(() => {
    const map = new Map<string, Transaction[]>()
    for (const item of data?.items ?? []) {
      const list = map.get(item.date) ?? []
      list.push(item)
      map.set(item.date, list)
    }
    return [...map.entries()]
  }, [data])

  const flatCategories = useMemo(
    () => categories.flatMap((c) => [c, ...c.children]),
    [categories],
  )

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))

  const exportHref = useMemo(() => {
    const { from, to } = monthRange(ym)
    return api.exportUrl({
      date_from: from,
      date_to: to,
      account_id: accountId === '' ? undefined : accountId,
      category_id: categoryId === '' ? undefined : categoryId,
      q: query.trim() || undefined,
    })
  }, [ym, accountId, categoryId, query])

  return (
    <>
      <div className="page-head">
        <div className="month-nav">
          <button
            className="btn-ghost btn-icon"
            aria-label={t('common.prevMonth')}
            onClick={() => setYm(shiftYearMonth(ym, -1))}
          >
            <Icon name="chevronLeft" />
          </button>
          <h1>{formatYearMonth(ym, locale)}</h1>
          <button
            className="btn-ghost btn-icon"
            aria-label={t('common.nextMonth')}
            onClick={() => setYm(shiftYearMonth(ym, 1))}
            disabled={ym >= currentYearMonth()}
          >
            <Icon name="chevronRight" />
          </button>
        </div>
        <div className="page-actions">
          <a className="btn-ghost link-btn-inline" href={exportHref} download>
            {t('reports.exportCsv')}
          </a>
          <button className="btn-ghost" onClick={() => setDialog('transfer')}>
            {t('action.transfer')}
          </button>
          <button className="btn-primary" onClick={() => setDialog('txn')}>
            {t('action.addTransaction')}
          </button>
        </div>
      </div>

      <div className="card filter-bar">
        <input
          type="text"
          className="filter-search"
          placeholder={t('txn.searchPlaceholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={accountId} onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">{t('txn.allAccounts')}</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <select
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">{t('txn.allCategories')}</option>
          {flatCategories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.parent_id ? '　' : ''}
              {c.name}
            </option>
          ))}
        </select>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={showTrash}
            onChange={(e) => setShowTrash(e.target.checked)}
          />
          <span>{t('txn.trash')}</span>
        </label>
      </div>

      {data && (
        <div className="list-summary">
          <span>{t('txn.count', { count: data.total })}</span>
          <span className="expense">−{formatJPY(data.sum_expense, locale)}</span>
          <span className="income">+{formatJPY(data.sum_income, locale)}</span>
        </div>
      )}

      {loading && !data ? (
        <p className="muted">{t('common.loading')}</p>
      ) : grouped.length === 0 ? (
        <div className="empty-state card">
          <p className="card-desc">{showTrash ? t('txn.trashEmpty') : t('txn.empty')}</p>
        </div>
      ) : (
        <div className={`card txn-list${showTrash ? ' trash' : ''}`}>
          {grouped.map(([date, items]) => (
            <div className="txn-group" key={date}>
              <div className="txn-date">
                {formatDateShort(date, locale)}
                <span className="muted"> {formatWeekday(date, locale)}</span>
              </div>
              {items.map((txn) => (
                <div
                  className="txn-row clickable"
                  key={txn.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => !showTrash && setEditing(txn)}
                  onKeyDown={(e) => {
                    if (!showTrash && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault()
                      setEditing(txn)
                    }
                  }}
                >
                  <span
                    className="txn-icon"
                    style={{ background: txn.category_color ?? 'var(--surface-2)' }}
                    aria-hidden="true"
                  >
                    {txn.transfer_group_id && txn.direction !== 'expense'
                      ? '⇄'
                      : (txn.category_icon ?? '·')}
                  </span>
                  <div className="txn-main">
                    <div className="txn-merchant">
                      {txn.merchant_raw || t('txn.noMerchant')}
                      {txn.installment_total && (
                        <span className="tag">
                          {t('txn.installmentTag', {
                            current: txn.installment_current ?? '?',
                            total: txn.installment_total,
                          })}
                        </span>
                      )}
                      {txn.exclude_from_analysis && (
                        <span className="tag" title={t('form.excludeFromAnalysisHint')}>
                          {t('txn.excludedTag')}
                        </span>
                      )}
                    </div>
                    <div className="txn-meta">
                      {txn.account_name}
                      {txn.category_name ? ` · ${txn.category_name}` : ''}
                      {txn.memo ? ` · ${txn.memo}` : ''}
                    </div>
                  </div>
                  <span className={`txn-amount mono ${txn.direction}`}>
                    {txn.direction === 'income' || txn.direction === 'transfer_in' ? '+' : '−'}
                    {formatJPY(txn.amount, locale)}
                  </span>
                  <span className="txn-actions" onClick={(e) => e.stopPropagation()}>
                    {showTrash ? (
                      <button className="btn-ghost" onClick={() => void restore(txn)}>
                        {t('txn.restore')}
                      </button>
                    ) : (
                      <button className="btn-ghost danger" onClick={() => void remove(txn)}>
                        {t('common.delete')}
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="pagination">
          <button
            className="btn-ghost btn-icon"
            aria-label={t('common.prevPage')}
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            <Icon name="chevronLeft" />
          </button>
          <span className="muted">
            {page} / {totalPages}
          </span>
          <button
            className="btn-ghost btn-icon"
            aria-label={t('common.nextPage')}
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
          >
            <Icon name="chevronRight" />
          </button>
        </div>
      )}

      <Modal
        open={dialog === 'txn' || editing !== null}
        title={editing ? t('action.editTransaction') : t('action.addTransaction')}
        onClose={() => {
          setDialog('none')
          setEditing(null)
        }}
        size="wide"
      >
        <TransactionForm
          existing={editing}
          onSaved={refresh}
          onCancel={() => {
            setDialog('none')
            setEditing(null)
          }}
          onDelete={
            editing
              ? async () => {
                  await remove(editing)
                }
              : undefined
          }
        />
      </Modal>

      <Modal
        open={dialog === 'transfer'}
        title={t('action.transfer')}
        onClose={() => setDialog('none')}
        size="wide"
      >
        <TransferForm onSaved={refresh} onCancel={() => setDialog('none')} />
      </Modal>
    </>
  )
}
