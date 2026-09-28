import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api, type Transaction } from '../api/client'
import { useLedger } from '../context/LedgerContext'
import { todayISO } from '../lib/format'
import { CategorySelect } from './CategorySelect'
import { MoneyInput } from './MoneyInput'

interface Props {
  /** 传入即为编辑模式 */
  existing?: Transaction | null
  onSaved: () => void
  onCancel: () => void
  /** 编辑时提供删除入口。窄屏没有行内操作按钮，删除只能从这里走 */
  onDelete?: () => void
}

export function TransactionForm({ existing, onSaved, onCancel, onDelete }: Props) {
  const { t } = useTranslation()
  const { accounts, categories } = useLedger()

  const [direction, setDirection] = useState<'expense' | 'income'>(
    existing?.direction === 'income' ? 'income' : 'expense',
  )
  const [date, setDate] = useState(existing?.date ?? todayISO())
  const [accountId, setAccountId] = useState<number | ''>(existing?.account_id ?? '')
  const [amount, setAmount] = useState(existing?.amount ?? 0)
  const [merchant, setMerchant] = useState(existing?.merchant_raw ?? '')
  const [categoryId, setCategoryId] = useState<number | null>(existing?.category_id ?? null)
  const [memo, setMemo] = useState(existing?.memo ?? '')
  const [excludeFromAnalysis, setExcludeFromAnalysis] = useState(existing?.exclude_from_analysis ?? false)

  const [showInstallment, setShowInstallment] = useState(!!existing?.installment_total)
  const [instCurrent, setInstCurrent] = useState<number | ''>(existing?.installment_current ?? '')
  const [instTotal, setInstTotal] = useState<number | ''>(existing?.installment_total ?? '')
  const [instTotalAmount, setInstTotalAmount] = useState(existing?.installment_total_amount ?? 0)

  const [suggestions, setSuggestions] = useState<string[]>([])
  const [autoFilled, setAutoFilled] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // 类别是否由用户手动指定过。手动指定后就不再被自动预测覆盖。
  const categoryTouched = useRef(!!existing?.category_id)

  // 默认选中第一个账户
  useEffect(() => {
    if (accountId === '' && accounts.length) setAccountId(accounts[0].id)
  }, [accounts, accountId])

  // 商家名变化时取补全候选，并按商家记忆预测类别
  useEffect(() => {
    const q = merchant.trim()
    if (!q) {
      setSuggestions([])
      return
    }
    const timer = setTimeout(() => {
      void api.merchantSuggestions(q).then(setSuggestions).catch(() => undefined)
      if (!categoryTouched.current) {
        void api
          .suggestCategory(q)
          .then((r) => {
            if (r.category_id && !categoryTouched.current) {
              setCategoryId(r.category_id)
              setAutoFilled(true)
            }
          })
          .catch(() => undefined)
      }
    }, 250)
    return () => clearTimeout(timer)
  }, [merchant])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (accountId === '') {
      setError(t('form.errorNoAccount'))
      return
    }
    if (amount <= 0) {
      setError(t('form.errorAmount'))
      return
    }

    const payload = {
      account_id: accountId,
      date,
      direction,
      amount,
      merchant_raw: merchant.trim(),
      category_id: categoryId,
      memo: memo.trim() || null,
      installment_current: showInstallment && instCurrent !== '' ? instCurrent : null,
      installment_total: showInstallment && instTotal !== '' ? instTotal : null,
      installment_total_amount: showInstallment && instTotalAmount ? instTotalAmount : null,
      exclude_from_analysis: excludeFromAnalysis,
    }

    setBusy(true)
    try {
      if (existing) {
        await api.updateTransaction(existing.id, payload)
      } else {
        await api.createTransaction(payload)
      }
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  // 转账的两条腿必须保持一致，金额与方向不允许单独改（后端也会拒绝）。
  // 此处只展示信息与删除入口，避免用户填了半天再被拒。
  if (existing?.transfer_group_id) {
    return (
      <div className="txn-form">
        <p className="alert info">{t('txn.transferNotEditable')}</p>
        <dl className="kv">
          <div>
            <dt>{t('form.date')}</dt>
            <dd>{existing.date}</dd>
          </div>
          <div>
            <dt>{t('form.account')}</dt>
            <dd>{existing.account_name}</dd>
          </div>
          <div>
            <dt>{t('form.amount')}</dt>
            <dd className="mono">{existing.amount.toLocaleString('en-US')}</dd>
          </div>
        </dl>
        <div className="form-actions">
          {onDelete && (
            <button type="button" className="btn-ghost danger form-delete" onClick={onDelete}>
              {t('common.delete')}
            </button>
          )}
          <button type="button" className="btn-primary" onClick={onCancel}>
            {t('common.close')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="txn-form">
      {error && <div className="alert error">{error}</div>}

      <div className="segmented" role="group">
        <button
          type="button"
          aria-pressed={direction === 'expense'}
          onClick={() => setDirection('expense')}
        >
          {t('direction.expense')}
        </button>
        <button
          type="button"
          aria-pressed={direction === 'income'}
          onClick={() => setDirection('income')}
        >
          {t('direction.income')}
        </button>
      </div>

      <div className="field">
        <label htmlFor="txn-amount">{t('form.amount')}</label>
        <MoneyInput id="txn-amount" value={amount} onChange={setAmount} autoFocus={!existing} />
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="txn-date">{t('form.date')}</label>
          <input
            id="txn-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            required
          />
        </div>

        <div className="field">
          <label htmlFor="txn-account">{t('form.account')}</label>
          <select
            id="txn-account"
            value={accountId}
            onChange={(e) => setAccountId(Number(e.target.value))}
            required
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="field">
        <label htmlFor="txn-merchant">{t('form.merchant')}</label>
        <input
          id="txn-merchant"
          type="text"
          list="merchant-suggestions"
          autoComplete="off"
          value={merchant}
          onChange={(e) => setMerchant(e.target.value)}
          placeholder={t('form.merchantPlaceholder')}
        />
        <datalist id="merchant-suggestions">
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </div>

      <div className="field">
        <label htmlFor="txn-category">{t('form.category')}</label>
        <CategorySelect
          id="txn-category"
          categories={categories}
          value={categoryId}
          type={direction}
          suggested={autoFilled && !categoryTouched.current}
          onChange={(id) => {
            categoryTouched.current = true
            setAutoFilled(false)
            setCategoryId(id)
          }}
        />
      </div>

      <div className="field">
        <label htmlFor="txn-memo">{t('form.memo')}</label>
        <input
          id="txn-memo"
          type="text"
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
        />
      </div>

      <div className="field">
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={excludeFromAnalysis}
            onChange={(e) => setExcludeFromAnalysis(e.target.checked)}
          />
          <span>{t('form.excludeFromAnalysis')}</span>
        </label>
        <p className="hint">{t('form.excludeFromAnalysisHint')}</p>
      </div>

      <div className="field">
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={showInstallment}
            onChange={(e) => setShowInstallment(e.target.checked)}
          />
          <span>{t('form.installment')}</span>
        </label>
        {showInstallment && (
          <>
            <p className="hint">{t('form.installmentHint')}</p>
            <div className="form-row">
              <div className="field">
                <label htmlFor="inst-current">{t('form.installmentCurrent')}</label>
                <input
                  id="inst-current"
                  type="number"
                  min={1}
                  value={instCurrent}
                  onChange={(e) => setInstCurrent(e.target.value ? Number(e.target.value) : '')}
                />
              </div>
              <div className="field">
                <label htmlFor="inst-total">{t('form.installmentTotal')}</label>
                <input
                  id="inst-total"
                  type="number"
                  min={1}
                  value={instTotal}
                  onChange={(e) => setInstTotal(e.target.value ? Number(e.target.value) : '')}
                />
              </div>
            </div>
            <div className="field">
              <label htmlFor="inst-amount">{t('form.installmentTotalAmount')}</label>
              <MoneyInput id="inst-amount" value={instTotalAmount} onChange={setInstTotalAmount} />
            </div>
          </>
        )}
      </div>

      <div className="form-actions">
        {existing && onDelete && (
          <button type="button" className="btn-ghost danger form-delete" onClick={onDelete}>
            {t('common.delete')}
          </button>
        )}
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
