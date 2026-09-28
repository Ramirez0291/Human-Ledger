import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ApiError,
  api,
  type Account,
  type AccountType,
  type ReconcileResult,
} from '../api/client'
import { Modal } from '../components/Modal'
import { MoneyInput } from '../components/MoneyInput'
import { useLedger } from '../context/LedgerContext'
import { formatJPY, todayISO } from '../lib/format'

const ACCOUNT_TYPES: AccountType[] = ['bank', 'credit_card', 'emoney', 'prepaid', 'investment', 'cash']

const PALETTE = [
  '#1f6f4f',
  '#3D8FE8',
  '#E8663D',
  '#8B5CF6',
  '#F59E0B',
  '#EC4899',
  '#06B6D4',
  '#64748B',
]

export function AccountsPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const { accounts, refreshAccounts } = useLedger()

  const [editing, setEditing] = useState<Account | null>(null)
  const [creating, setCreating] = useState(false)
  const [reconciling, setReconciling] = useState<Account | null>(null)

  return (
    <>
      <div className="page-head">
        <h1>{t('nav.accounts')}</h1>
        <div className="page-actions">
          <button className="btn-primary" onClick={() => setCreating(true)}>
            {t('account.add')}
          </button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <div className="empty-state card">
          <h2>{t('account.emptyTitle')}</h2>
          <p className="card-desc">{t('account.emptyDesc')}</p>
        </div>
      ) : (
        <div className="card">
          <ul className="account-manage-list">
            {accounts.map((a) => (
              <li key={a.id}>
                <span className="dot" style={{ background: a.color ?? 'var(--border-strong)' }} />
                <div className="account-info">
                  <div className="account-name">{a.name}</div>
                  <div className="account-meta">
                    {t(`accountType.${a.type}`)}
                    {a.institution ? ` · ${a.institution}` : ''}
                    {' · '}
                    {t('account.txnCount', { count: a.transaction_count })}
                    {a.last_reconcile_diff !== null && a.last_reconcile_diff !== 0 && (
                      <span className="warn-text">
                        {' · '}
                        {t('account.diffWarn', {
                          amount: formatJPY(a.last_reconcile_diff, locale),
                        })}
                      </span>
                    )}
                  </div>
                </div>
                <span className={`mono account-balance ${a.balance < 0 ? 'expense' : ''}`}>
                  {formatJPY(a.balance, locale)}
                </span>
                <span className="txn-actions">
                  <button className="btn-ghost" onClick={() => setReconciling(a)}>
                    {t('account.reconcile')}
                  </button>
                  <button className="btn-ghost" onClick={() => setEditing(a)}>
                    {t('common.edit')}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Modal
        open={creating || editing !== null}
        title={editing ? t('account.edit') : t('account.add')}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
      >
        <AccountForm
          existing={editing}
          onSaved={async () => {
            setCreating(false)
            setEditing(null)
            await refreshAccounts()
          }}
          onCancel={() => {
            setCreating(false)
            setEditing(null)
          }}
        />
      </Modal>

      <Modal
        open={reconciling !== null}
        title={t('account.reconcile')}
        onClose={() => setReconciling(null)}
      >
        {reconciling && (
          <ReconcileForm
            account={reconciling}
            onDone={async () => {
              await refreshAccounts()
            }}
            onClose={() => setReconciling(null)}
          />
        )}
      </Modal>
    </>
  )
}

// --------------------------------------------------------------------------

function AccountForm({
  existing,
  onSaved,
  onCancel,
}: {
  existing: Account | null
  onSaved: () => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(existing?.name ?? '')
  const [type, setType] = useState<AccountType>(existing?.type ?? 'bank')
  const [institution, setInstitution] = useState(existing?.institution ?? '')
  const [openingBalance, setOpeningBalance] = useState(existing?.opening_balance ?? 0)
  const [color, setColor] = useState(existing?.color ?? PALETTE[0])
  const [closingDay, setClosingDay] = useState<number | ''>(existing?.closing_day ?? '')
  const [paymentDay, setPaymentDay] = useState<number | ''>(existing?.payment_day ?? '')
  const [archived, setArchived] = useState(existing?.is_archived ?? false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const payload = {
        name: name.trim(),
        type,
        institution: institution.trim() || null,
        opening_balance: openingBalance,
        color,
        closing_day: type === 'credit_card' && closingDay !== '' ? closingDay : null,
        payment_day: type === 'credit_card' && paymentDay !== '' ? paymentDay : null,
        is_archived: archived,
      }
      if (existing) await api.updateAccount(existing.id, payload)
      else await api.createAccount(payload)
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="txn-form">
      {error && <div className="alert error">{error}</div>}

      <div className="field">
        <label htmlFor="acc-name">{t('account.name')}</label>
        <input
          id="acc-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('account.namePlaceholder')}
          required
          autoFocus
        />
      </div>

      <div className="field">
        <label htmlFor="acc-type">{t('account.type')}</label>
        <select id="acc-type" value={type} onChange={(e) => setType(e.target.value as AccountType)}>
          {ACCOUNT_TYPES.map((tp) => (
            <option key={tp} value={tp}>
              {t(`accountType.${tp}`)}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="acc-institution">{t('account.institution')}</label>
        <input
          id="acc-institution"
          type="text"
          value={institution}
          onChange={(e) => setInstitution(e.target.value)}
          placeholder={t('account.institutionPlaceholder')}
        />
        <span className="hint">{t('account.institutionHint')}</span>
      </div>

      <div className="field">
        <label htmlFor="acc-opening">{t('account.openingBalance')}</label>
        <MoneyInput id="acc-opening" value={openingBalance} onChange={setOpeningBalance} />
        <span className="hint">{t('account.openingBalanceHint')}</span>
      </div>

      {type === 'credit_card' && (
        <div className="form-row">
          <div className="field">
            <label htmlFor="acc-closing">{t('account.closingDay')}</label>
            <input
              id="acc-closing"
              type="number"
              min={1}
              max={31}
              value={closingDay}
              onChange={(e) => setClosingDay(e.target.value ? Number(e.target.value) : '')}
            />
          </div>
          <div className="field">
            <label htmlFor="acc-payment">{t('account.paymentDay')}</label>
            <input
              id="acc-payment"
              type="number"
              min={1}
              max={31}
              value={paymentDay}
              onChange={(e) => setPaymentDay(e.target.value ? Number(e.target.value) : '')}
            />
          </div>
        </div>
      )}

      <div className="field">
        <label>{t('account.color')}</label>
        <div className="color-picker">
          {PALETTE.map((c) => (
            <button
              key={c}
              type="button"
              className="color-swatch"
              style={{ background: c }}
              aria-pressed={color === c}
              aria-label={c}
              onClick={() => setColor(c)}
            />
          ))}
        </div>
      </div>

      {existing && (
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => setArchived(e.target.checked)}
          />
          <span>{t('account.archive')}</span>
        </label>
      )}

      <div className="form-actions">
        <button type="button" className="btn-ghost" onClick={onCancel}>
          {t('common.cancel')}
        </button>
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </form>
  )
}

// --------------------------------------------------------------------------

function ReconcileForm({
  account,
  onDone,
  onClose,
}: {
  account: Account
  onDone: () => void
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const [date, setDate] = useState(todayISO())
  const [actual, setActual] = useState(0)
  const [result, setResult] = useState<ReconcileResult | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const res = await api.reconcile(account.id, { date, actual_balance: actual })
      setResult(res)
      onDone()
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    const ok = result.diff === 0
    return (
      <div className="stack-sm">
        <div className={`alert ${ok ? 'ok' : 'warn'}`}>
          {ok
            ? t('account.reconcileOk')
            : t('account.reconcileDiff', { amount: formatJPY(result.diff, locale) })}
        </div>
        <dl className="kv">
          <div>
            <dt>{t('account.computedBalance')}</dt>
            <dd className="mono">{formatJPY(result.computed_balance, locale)}</dd>
          </div>
          <div>
            <dt>{t('account.actualBalance')}</dt>
            <dd className="mono">{formatJPY(result.actual_balance, locale)}</dd>
          </div>
        </dl>
        {!ok && <p className="hint">{t('account.reconcileHint')}</p>}
        <div className="form-actions">
          <button className="btn-primary" onClick={onClose}>
            {t('common.close')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="txn-form">
      <p className="alert info">{t('account.reconcileExplainer')}</p>

      <div className="field">
        <label htmlFor="rec-date">{t('form.date')}</label>
        <input id="rec-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>

      <div className="field">
        <label htmlFor="rec-balance">{t('account.actualBalance')}</label>
        <MoneyInput id="rec-balance" value={actual} onChange={setActual} autoFocus />
        <span className="hint">{t('account.actualBalanceHint')}</span>
      </div>

      <div className="form-actions">
        <button type="button" className="btn-ghost" onClick={onClose}>
          {t('common.cancel')}
        </button>
        <button type="submit" className="btn-primary" disabled={busy}>
          {t('account.checkBalance')}
        </button>
      </div>
    </form>
  )
}
