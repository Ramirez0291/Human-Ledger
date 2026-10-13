import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api, type SpecialBudget, type SpecialBudgetKind } from '../../api/client'
import { useLedger } from '../../context/LedgerContext'
import { todayISO } from '../../lib/format'
import { CategorySelect } from '../CategorySelect'
import { MoneyInput } from '../MoneyInput'
import { KIND_ICON, specialPresets } from './BudgetBits'

interface Props {
  existing?: SpecialBudget | null
  onSaved: () => void
  onCancel: () => void
  onDelete?: () => void
}

const KINDS: SpecialBudgetKind[] = ['holiday', 'bonus', 'treat', 'other']

/**
 * 特别预算：一段日期里额外多给一笔。
 * 预设把常见的由头（节假日按账本地区：黄金周 / お盆 或 春节 / 国庆；发奖金、周末犒劳自己）一键填好日期和名字。
 */
export function SpecialBudgetForm({ existing, onSaved, onCancel, onDelete }: Props) {
  const { t } = useTranslation()
  const { categories } = useLedger()
  const presets = useMemo(() => specialPresets(), [])

  const [kind, setKind] = useState<SpecialBudgetKind>(existing?.kind ?? 'holiday')
  const [name, setName] = useState(existing?.name ?? '')
  const [amount, setAmount] = useState(existing?.amount ?? 0)
  const [from, setFrom] = useState(existing?.date_from ?? todayISO())
  const [to, setTo] = useState(existing?.date_to ?? todayISO())
  const [categoryId, setCategoryId] = useState<number | null>(existing?.category_id ?? null)
  const [memo, setMemo] = useState(existing?.memo ?? '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function applyPreset(key: string) {
    const p = presets.find((x) => x.key === key)
    if (!p) return
    setKind(p.kind)
    setFrom(p.from)
    setTo(p.to)
    setName(t(`budget.preset.${p.key}`))
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!name.trim()) return setError(t('budget.errorName'))
    if (amount <= 0) return setError(t('form.errorAmount'))
    if (to < from) return setError(t('budget.errorRange'))
    const body = {
      name: name.trim(),
      kind,
      amount,
      date_from: from,
      date_to: to,
      category_id: categoryId,
      memo: memo.trim() || null,
    }
    setBusy(true)
    try {
      if (existing) {
        await api.updateSpecialBudget(existing.id, {
          ...body,
          clear_category: categoryId === null,
        })
      } else {
        await api.createSpecialBudget(body)
      }
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

      {!existing && (
        <div className="field">
          <span className="label-like">{t('budget.presets')}</span>
          <div className="chip-row">
            {presets.map((p) => (
              <button key={p.key} type="button" className="chip" onClick={() => applyPreset(p.key)}>
                {KIND_ICON[p.kind]} {t(`budget.preset.${p.key}`)}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="field">
        <span className="label-like">{t('budget.kind')}</span>
        <div className="segmented" role="group">
          {KINDS.map((k) => (
            <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>
              {KIND_ICON[k]} {t(`budget.kinds.${k}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="sb-name">{t('budget.specialName')}</label>
          <input id="sb-name" type="text" value={name} maxLength={128} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sb-amount">{t('budget.extraAmount')}</label>
          <MoneyInput id="sb-amount" value={amount} onChange={setAmount} />
        </div>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="sb-from">{t('budget.from')}</label>
          <input id="sb-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sb-to">{t('budget.to')}</label>
          <input id="sb-to" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>

      <div className="field">
        <label htmlFor="sb-cat">{t('budget.specialCategory')}</label>
        <CategorySelect
          id="sb-cat"
          categories={categories}
          value={categoryId}
          onChange={setCategoryId}
          type="expense"
          emptyLabel={t('budget.anyCategory')}
        />
        <span className="hint">{t('budget.specialCategoryHint')}</span>
      </div>

      <div className="field">
        <label htmlFor="sb-memo">{t('form.memo')}</label>
        <input id="sb-memo" type="text" value={memo} onChange={(e) => setMemo(e.target.value)} />
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
