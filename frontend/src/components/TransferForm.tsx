import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api } from '../api/client'
import { useLedger } from '../context/LedgerContext'
import { todayISO } from '../lib/format'
import { CategorySelect } from './CategorySelect'
import { MoneyInput } from './MoneyInput'

interface Props {
  onSaved: () => void
  onCancel: () => void
}

/**
 * 账户间转账。
 *
 * 这是一个独立表单而非普通记账的一个方向选项，因为转账在数据上是**成对**的
 * 两条记录，且不计入收支统计。典型用途：ATM 取现、PayPay 充值、
 * 信用卡还款、交通 IC 充值。
 */
export function TransferForm({ onSaved, onCancel }: Props) {
  const { t } = useTranslation()
  const { accounts, categories } = useLedger()

  const [fromId, setFromId] = useState<number | ''>('')
  const [toId, setToId] = useState<number | ''>('')
  const [date, setDate] = useState(todayISO())
  const [amount, setAmount] = useState(0)
  const [memo, setMemo] = useState('')
  const [fee, setFee] = useState(0)
  const [feeCategoryId, setFeeCategoryId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (accounts.length >= 1 && fromId === '') setFromId(accounts[0].id)
    if (accounts.length >= 2 && toId === '') setToId(accounts[1].id)
  }, [accounts, fromId, toId])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (fromId === '' || toId === '') {
      setError(t('form.errorNoAccount'))
      return
    }
    if (fromId === toId) {
      setError(t('transfer.errorSameAccount'))
      return
    }
    if (amount <= 0) {
      setError(t('form.errorAmount'))
      return
    }

    setBusy(true)
    try {
      await api.createTransfer({
        from_account_id: fromId,
        to_account_id: toId,
        date,
        amount,
        memo: memo.trim() || null,
        fee,
        fee_category_id: fee > 0 ? feeCategoryId : null,
      })
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

      <p className="alert info">{t('transfer.explainer')}</p>

      <div className="field">
        <label htmlFor="tr-amount">{t('form.amount')}</label>
        <MoneyInput id="tr-amount" value={amount} onChange={setAmount} autoFocus />
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="tr-from">{t('transfer.from')}</label>
          <select id="tr-from" value={fromId} onChange={(e) => setFromId(Number(e.target.value))}>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tr-to">{t('transfer.to')}</label>
          <select id="tr-to" value={toId} onChange={(e) => setToId(Number(e.target.value))}>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="field">
        <label htmlFor="tr-date">{t('form.date')}</label>
        <input id="tr-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>

      <div className="field">
        <label htmlFor="tr-fee">{t('transfer.fee')}</label>
        <MoneyInput id="tr-fee" value={fee} onChange={setFee} />
        <span className="hint">{t('transfer.feeHint')}</span>
      </div>

      {fee > 0 && (
        <div className="field">
          <label htmlFor="tr-fee-cat">{t('transfer.feeCategory')}</label>
          <CategorySelect
            id="tr-fee-cat"
            categories={categories}
            value={feeCategoryId}
            type="expense"
            onChange={setFeeCategoryId}
          />
        </div>
      )}

      <div className="field">
        <label htmlFor="tr-memo">{t('form.memo')}</label>
        <input id="tr-memo" type="text" value={memo} onChange={(e) => setMemo(e.target.value)} />
      </div>

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
