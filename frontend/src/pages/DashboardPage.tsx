import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, type Summary } from '../api/client'
import { Icon } from '../components/Icon'
import { Modal } from '../components/Modal'
import { TransactionForm } from '../components/TransactionForm'
import { TransferForm } from '../components/TransferForm'
import { useLedger } from '../context/LedgerContext'
import {
  currentYearMonth,
  formatJPY,
  formatYearMonth,
  shiftYearMonth,
} from '../lib/format'

export function DashboardPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const { accounts, refreshAccounts } = useLedger()

  const [ym, setYm] = useState(currentYearMonth())
  const [summary, setSummary] = useState<Summary | null>(null)
  const [dialog, setDialog] = useState<'none' | 'txn' | 'transfer'>('none')

  const load = useCallback(async () => {
    setSummary(await api.summary(ym))
  }, [ym])

  useEffect(() => {
    void load()
  }, [load])

  async function afterSave() {
    setDialog('none')
    await Promise.all([load(), refreshAccounts()])
  }

  const maxBreakdown = summary?.expense_breakdown[0]?.amount ?? 0

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
          <button className="btn-ghost" onClick={() => setDialog('transfer')}>
            {t('action.transfer')}
          </button>
          <button className="btn-primary" onClick={() => setDialog('txn')}>
            {t('action.addTransaction')}
          </button>
        </div>
      </div>

      {accounts.length === 0 && (
        <div className="empty-state card">
          <h2>{t('dashboard.emptyTitle')}</h2>
          <p className="card-desc">{t('dashboard.emptyDesc')}</p>
          <Link className="btn-primary link-btn" to="/accounts">
            {t('dashboard.emptyAction')}
          </Link>
        </div>
      )}

      {summary && accounts.length > 0 && (
        <>
          <div className="stat-row">
            <div className="stat">
              <span className="stat-label">{t('dashboard.expense')}</span>
              <span className="stat-value expense">{formatJPY(summary.expense, locale)}</span>
            </div>
            <div className="stat">
              <span className="stat-label">{t('dashboard.income')}</span>
              <span className="stat-value income">{formatJPY(summary.income, locale)}</span>
            </div>
            <div className="stat">
              <span className="stat-label">{t('dashboard.net')}</span>
              <span className={`stat-value ${summary.net >= 0 ? 'income' : 'expense'}`}>
                {formatJPY(summary.net, locale)}
              </span>
            </div>
          </div>

          {summary.reconcile_alerts.length > 0 && (
            <div className="card alert-card">
              <h2>{t('dashboard.reconcileAlertTitle')}</h2>
              <p className="card-desc">{t('dashboard.reconcileAlertDesc')}</p>
              <ul className="alert-list">
                {summary.reconcile_alerts.map((a) => (
                  <li key={a.account_id}>
                    <span>{a.account_name}</span>
                    <span className="mono">{formatJPY(a.diff, locale)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="card">
            <div className="card-header">
              <h2>{t('dashboard.accountsTitle')}</h2>
            </div>
            <ul className="account-list">
              {summary.accounts.map((a) => (
                <li key={a.id}>
                  <span className="dot" style={{ background: a.color ?? 'var(--border-strong)' }} />
                  <span className="account-name">{a.name}</span>
                  <span className={`mono ${a.balance < 0 ? 'expense' : ''}`}>
                    {formatJPY(a.balance, locale)}
                  </span>
                </li>
              ))}
              <li className="total-row">
                <span className="account-name">{t('dashboard.totalBalance')}</span>
                <span className="mono">{formatJPY(summary.total_balance, locale)}</span>
              </li>
            </ul>
          </div>

          <div className="card">
            <div className="card-header">
              <h2>{t('dashboard.breakdownTitle')}</h2>
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
                    <span className="mono breakdown-amount">{formatJPY(b.amount, locale)}</span>
                  </li>
                ))}
              </ul>
            )}
            {summary.uncategorized_expense > 0 && (
              <p className="hint" style={{ marginTop: 12 }}>
                {t('dashboard.uncategorized', {
                  amount: formatJPY(summary.uncategorized_expense, locale),
                })}
              </p>
            )}
          </div>
        </>
      )}

      <Modal
        open={dialog === 'txn'}
        title={t('action.addTransaction')}
        onClose={() => setDialog('none')}
        size="wide"
      >
        <TransactionForm onSaved={afterSave} onCancel={() => setDialog('none')} />
      </Modal>

      <Modal
        open={dialog === 'transfer'}
        title={t('action.transfer')}
        onClose={() => setDialog('none')}
        size="wide"
      >
        <TransferForm onSaved={afterSave} onCancel={() => setDialog('none')} />
      </Modal>
    </>
  )
}
