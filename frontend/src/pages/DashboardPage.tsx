import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, type BudgetStatus, type Summary, type Transaction } from '../api/client'
import { BudgetWidget } from '../components/budget/BudgetWidget'
import { Icon } from '../components/Icon'
import { Modal } from '../components/Modal'
import { TransactionForm } from '../components/TransactionForm'
import { TransferForm } from '../components/TransferForm'
import { useLedger } from '../context/LedgerContext'
import { regionContext } from '../lib/region'
import {
  currentYearMonth,
  formatDateShort,
  formatMoney,
  formatYearMonth,
  monthRange,
  shiftYearMonth,
} from '../lib/format'
import { WIDE_QUERY, useMediaQuery } from '../lib/useMediaQuery'

const RECENT = 8

/**
 * 首页。
 *
 * 宽屏（≥1100px）是「左边记账、右边看报表」的工作台：左栏常驻记账表单（连续记账，
 * 保存后清空金额继续下一笔）与最近记录，右栏是本月收支、预算、账户与类目。
 * 每记一笔右栏随之刷新，记账的同时就能看到预算还剩多少。
 * 窄屏保持原样：顶部按钮打开弹窗记账。
 */
export function DashboardPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const { accounts, refreshAccounts } = useLedger()
  const wide = useMediaQuery(WIDE_QUERY)

  const [ym, setYm] = useState(currentYearMonth())
  const [summary, setSummary] = useState<Summary | null>(null)
  const [budget, setBudget] = useState<BudgetStatus | null>(null)
  const [recent, setRecent] = useState<Transaction[]>([])
  const [dialog, setDialog] = useState<'none' | 'txn' | 'transfer'>('none')
  const [entry, setEntry] = useState<'txn' | 'transfer'>('txn')

  const load = useCallback(async () => {
    const { from, to } = monthRange(ym)
    const [s, b, r] = await Promise.all([
      api.summary(ym),
      api.budgetStatus(ym).catch(() => null),
      api.transactions({ date_from: from, date_to: to, page_size: RECENT }).catch(() => null),
    ])
    setSummary(s)
    setBudget(b)
    setRecent(r?.items ?? [])
  }, [ym])

  useEffect(() => {
    void load()
  }, [load])

  async function afterSave() {
    setDialog('none')
    await Promise.all([load(), refreshAccounts()])
  }

  const maxBreakdown = summary?.expense_breakdown[0]?.amount ?? 0
  const hasAccounts = accounts.length > 0

  const report = summary && hasAccounts && (
    <>
      <div className="stat-row">
        <div className="stat">
          <span className="stat-label">{t('dashboard.expense')}</span>
          <span className="stat-value expense">{formatMoney(summary.expense, locale)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">{t('dashboard.income')}</span>
          <span className="stat-value income">{formatMoney(summary.income, locale)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">{t('dashboard.net')}</span>
          <span className={`stat-value ${summary.net >= 0 ? 'income' : 'expense'}`}>
            {formatMoney(summary.net, locale)}
          </span>
        </div>
      </div>

      {budget && <BudgetWidget status={budget} />}

      {summary.reconcile_alerts.length > 0 && (
        <div className="card alert-card">
          <h2>{t('dashboard.reconcileAlertTitle')}</h2>
          <p className="card-desc">{t('dashboard.reconcileAlertDesc')}</p>
          <ul className="alert-list">
            {summary.reconcile_alerts.map((a) => (
              <li key={a.account_id}>
                <span>{a.account_name}</span>
                <span className="mono">{formatMoney(a.diff, locale)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="dashboard-pair">
        <div className="card">
          <div className="card-header row">
            <h2>{t('dashboard.breakdownTitle')}</h2>
            <span className="spacer" />
            <Link className="rank-link small" to="/reports">
              {t('dashboard.toReports')} →
            </Link>
          </div>
          {summary.expense_breakdown.length === 0 ? (
            <p className="card-desc">{t('dashboard.breakdownEmpty')}</p>
          ) : (
            <ul className="breakdown-list">
              {summary.expense_breakdown.map((b) => (
                <li key={b.category_id}>
                  <span className="breakdown-name">
                    <span aria-hidden="true">{b.icon}</span> {b.name}
                  </span>
                  <span className="breakdown-bar">
                    <span
                      style={{
                        width: `${maxBreakdown ? (b.amount / maxBreakdown) * 100 : 0}%`,
                        background: b.color ?? 'var(--accent)',
                      }}
                    />
                  </span>
                  <span className="mono breakdown-amount">{formatMoney(b.amount, locale)}</span>
                </li>
              ))}
            </ul>
          )}
          {summary.uncategorized_expense > 0 && (
            <p className="hint" style={{ marginTop: 12 }}>
              {t('dashboard.uncategorized', {
                amount: formatMoney(summary.uncategorized_expense, locale),
              })}
            </p>
          )}
        </div>

        <div className="card">
          <div className="card-header">
            <h2>{t('dashboard.accountsTitle')}</h2>
          </div>
          <ul className="account-list">
            {summary.accounts.map((a) => (
              <li key={a.id}>
                <span className="dot" style={{ background: a.color ?? 'var(--border-strong)' }} />
                <span className="account-name">{a.name}</span>
                <span className={`mono ${a.balance < 0 ? 'expense' : ''}`}>{formatMoney(a.balance, locale)}</span>
              </li>
            ))}
            <li className="total-row">
              <span className="account-name">{t('dashboard.totalBalance')}</span>
              <span className="mono">{formatMoney(summary.total_balance, locale)}</span>
            </li>
          </ul>
        </div>
      </div>
    </>
  )

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
        {!wide && (
          <div className="page-actions">
            <button className="btn-ghost" onClick={() => setDialog('transfer')}>
              {t('action.transfer')}
            </button>
            <button className="btn-primary" onClick={() => setDialog('txn')}>
              {t('action.addTransaction')}
            </button>
          </div>
        )}
      </div>

      {!hasAccounts && (
        <div className="empty-state card">
          <h2>{t('dashboard.emptyTitle')}</h2>
          <p className="card-desc">{t('dashboard.emptyDesc', { context: regionContext() })}</p>
          <Link className="btn-primary link-btn" to={regionContext() === 'CN' ? '/import' : '/accounts'}>
            {t('dashboard.emptyAction', { context: regionContext() })}
          </Link>
        </div>
      )}

      {wide && hasAccounts ? (
        <div className="workspace">
          <aside className="workspace-entry">
            <div className="card">
              <div className="segmented entry-toggle" role="group">
                <button type="button" aria-pressed={entry === 'txn'} onClick={() => setEntry('txn')}>
                  {t('action.addTransaction')}
                </button>
                <button type="button" aria-pressed={entry === 'transfer'} onClick={() => setEntry('transfer')}>
                  {t('action.transfer')}
                </button>
              </div>
              {entry === 'txn' ? (
                <TransactionForm quick onSaved={() => void afterSave()} />
              ) : (
                <TransferForm quick onSaved={() => void afterSave()} />
              )}
            </div>

            <div className="card">
              <div className="card-header row">
                <h2>{t('dashboard.recentTitle')}</h2>
                <span className="spacer" />
                <Link className="rank-link small" to={`/transactions?ym=${ym}`}>
                  {t('dashboard.allTransactions')} →
                </Link>
              </div>
              {recent.length === 0 ? (
                <p className="card-desc">{t('dashboard.recentEmpty')}</p>
              ) : (
                <ul className="recent-list">
                  {recent
                    .filter((x) => x.direction !== 'transfer_in')
                    .map((x) => (
                      <li key={x.id}>
                        <span className="recent-icon" aria-hidden="true">
                          {x.direction.startsWith('transfer') ? '⇄' : (x.category_icon ?? '·')}
                        </span>
                        <span className="recent-main">
                          <span className="recent-merchant">{x.merchant_raw || t('txn.noMerchant')}</span>
                          <span className="muted small">
                            {formatDateShort(x.date, locale)} · {x.account_name}
                          </span>
                        </span>
                        <span
                          className={`mono ${x.direction === 'income' ? 'income' : x.direction === 'expense' ? 'expense' : 'muted'}`}
                        >
                          {x.direction === 'income' ? '+' : x.direction === 'expense' ? '−' : ''}
                          {formatMoney(x.amount, locale)}
                        </span>
                      </li>
                    ))}
                </ul>
              )}
            </div>
          </aside>
          <section className="workspace-report">{report}</section>
        </div>
      ) : (
        report
      )}

      <Modal open={dialog === 'txn'} title={t('action.addTransaction')} onClose={() => setDialog('none')} size="wide">
        <TransactionForm onSaved={afterSave} onCancel={() => setDialog('none')} />
      </Modal>

      <Modal open={dialog === 'transfer'} title={t('action.transfer')} onClose={() => setDialog('none')} size="wide">
        <TransferForm onSaved={afterSave} onCancel={() => setDialog('none')} />
      </Modal>
    </>
  )
}
