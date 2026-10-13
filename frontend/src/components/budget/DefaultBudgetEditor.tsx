import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type BudgetSuggestion, type DefaultBudget } from '../../api/client'
import { useLedger } from '../../context/LedgerContext'
import { formatMoney } from '../../lib/format'
import { MoneyInput } from '../MoneyInput'

interface Props {
  defaults: DefaultBudget[]
  onSaved: () => void | Promise<void>
}

/**
 * 默认预算：每个月自动沿用。总额 + 各大分類（可只填几个）。
 *
 * 「按过去的习惯填入」只是把建议值填进输入框，用户看过、改过、点保存才生效——
 * 预算是用户给自己定的目标，不替他决定。
 */
export function DefaultBudgetEditor({ defaults, onSaved }: Props) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const { categories } = useLedger()
  const groups = useMemo(() => categories.filter((c) => c.type === 'expense' && !c.is_hidden), [categories])

  const initial = useMemo(() => {
    const m: Record<string, number> = {}
    for (const b of defaults) m[b.category_id === null ? 'total' : String(b.category_id)] = b.amount
    return m
  }, [defaults])

  const [values, setValues] = useState<Record<string, number>>(initial)
  const [suggestion, setSuggestion] = useState<BudgetSuggestion | null>(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => setValues(initial), [initial])

  const dirty = Object.keys({ ...initial, ...values }).some((k) => (initial[k] ?? 0) !== (values[k] ?? 0))
  const categorySum = groups.reduce((n, g) => n + (values[String(g.id)] ?? 0), 0)

  async function fillSuggestion() {
    const s = suggestion ?? (await api.budgetSuggest())
    setSuggestion(s)
    const next = { ...values }
    if (s.total) next.total = s.total
    for (const c of s.categories) next[String(c.category_id)] = c.amount
    setValues(next)
    setSaved(false)
  }

  async function save() {
    setBusy(true)
    try {
      const keys = new Set([...Object.keys(initial), ...Object.keys(values)])
      for (const k of keys) {
        const before = initial[k] ?? 0
        const after = values[k] ?? 0
        if (before === after) continue
        const categoryId = k === 'total' ? null : Number(k)
        if (after > 0) {
          await api.setDefaultBudget({
            category_id: categoryId,
            amount: after,
          })
        } else {
          const row = defaults.find((b) => b.category_id === categoryId)
          if (row) await api.deleteDefaultBudget(row.id)
        }
      }
      setSaved(true)
      await onSaved()
    } finally {
      setBusy(false)
    }
  }

  const hintFor = (id: number) => suggestion?.categories.find((c) => c.category_id === id)

  return (
    <div className="budget-editor">
      <div className="budget-editor-head">
        <p className="card-desc">{t('budget.defaultsDesc')}</p>
        <button type="button" className="btn-ghost small" onClick={() => void fillSuggestion()}>
          {t('budget.fillSuggestion')}
        </button>
      </div>
      {suggestion && (
        <p className="hint">
          {suggestion.basis_months
            ? t('budget.suggestionBasis', { count: suggestion.basis_months })
            : t('budget.suggestionNone')}
        </p>
      )}

      <div className="budget-editor-row total">
        <label htmlFor="bd-total">{t('budget.totalBudget')}</label>
        <MoneyInput
          id="bd-total"
          value={values.total ?? 0}
          onChange={(v) => setValues({ ...values, total: v })}
          placeholder={t('budget.notSet')}
        />
      </div>
      {categorySum > 0 && (values.total ?? 0) > 0 && categorySum > (values.total ?? 0) && (
        <p className="hint warn-text">
          {t('budget.categoriesExceedTotal', {
            amount: formatMoney(categorySum, locale),
          })}
        </p>
      )}

      <ul className="budget-editor-list">
        {groups.map((g) => {
          const hint = hintFor(g.id)
          return (
            <li key={g.id}>
              <label htmlFor={`bd-${g.id}`}>
                <span aria-hidden="true">{g.icon}</span> {g.name}
              </label>
              <MoneyInput
                id={`bd-${g.id}`}
                value={values[String(g.id)] ?? 0}
                onChange={(v) => setValues({ ...values, [String(g.id)]: v })}
                placeholder={t('budget.notSet')}
              />
              {hint && (
                <span className="muted small">
                  {t('budget.typical', {
                    amount: formatMoney(hint.amount, locale),
                  })}
                </span>
              )}
            </li>
          )
        })}
      </ul>

      <div className="form-actions">
        {saved && !dirty && <span className="muted small">{t('budget.saved')}</span>}
        <button type="button" className="btn-ghost" disabled={!dirty || busy} onClick={() => setValues(initial)}>
          {t('common.reset')}
        </button>
        <button type="button" className="btn-primary" disabled={!dirty || busy} onClick={() => void save()}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </div>
  )
}
