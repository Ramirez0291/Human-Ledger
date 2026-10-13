import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, type BudgetStatus, type DefaultBudget, type SpecialBudget } from '../api/client'
import { BudgetBar, KIND_ICON, paceText, statusSentence, statusTone } from '../components/budget/BudgetBits'
import { DefaultBudgetEditor } from '../components/budget/DefaultBudgetEditor'
import { SpecialBudgetForm } from '../components/budget/SpecialBudgetForm'
import { BudgetChart } from '../components/charts/BudgetChart'
import { Icon } from '../components/Icon'
import { Modal } from '../components/Modal'
import {
  currentYearMonth,
  formatCompactMoney,
  formatDateShort,
  formatMoney,
  formatYearMonth,
  shiftYearMonth,
} from '../lib/format'

/**
 * 预算页（需求书 F7）。
 *
 * 顶上一句话告诉用户「按现在的花法月底会怎样」，下面依次是：累计支出图（实际 + 预测）、
 * 各类目、特别预算、默认预算的设置。
 */
export function BudgetPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const [ym, setYm] = useState(currentYearMonth())
  const [status, setStatus] = useState<BudgetStatus | null>(null)
  const [defaults, setDefaults] = useState<DefaultBudget[]>([])
  const [specials, setSpecials] = useState<SpecialBudget[]>([])
  const [editing, setEditing] = useState<SpecialBudget | 'new' | null>(null)
  const [showSetup, setShowSetup] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const [s, b] = await Promise.all([api.budgetStatus(ym), api.budgets()])
      setStatus(s)
      setDefaults(b.defaults)
      setSpecials(b.specials)
    } catch {
      setError(t('common.error'))
    }
  }, [ym, t])

  useEffect(() => {
    void load()
  }, [load])

  async function removeSpecial(s: SpecialBudget) {
    if (!window.confirm(t('budget.confirmDeleteSpecial', { name: s.name }))) return
    await api.deleteSpecialBudget(s.id)
    setEditing(null)
    await load()
  }

  const noBudget = defaults.length === 0
  const finished = status ? status.elapsed_days >= status.days_in_month : false
  const total = status?.total
  const inMonth = new Set(status?.specials.map((s) => s.id))
  const otherSpecials = specials.filter((s) => !inMonth.has(s.id))

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
          <h1>
            {t('nav.budget')} · {formatYearMonth(ym, locale)}
          </h1>
          <button
            className="btn-ghost btn-icon"
            aria-label={t('common.nextMonth')}
            onClick={() => setYm(shiftYearMonth(ym, 1))}
          >
            <Icon name="chevronRight" />
          </button>
          {ym !== currentYearMonth() && (
            <button className="btn-ghost small" onClick={() => setYm(currentYearMonth())}>
              {t('reports.thisMonth')}
            </button>
          )}
        </div>
        <div className="page-actions">
          <button className="btn-ghost" onClick={() => setShowSetup((v) => !v)}>
            {t('budget.editDefaults')}
          </button>
          <button className="btn-primary" onClick={() => setEditing('new')}>
            {t('budget.addSpecial')}
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="budget-layout">
        <div>
          {status && total && (
            <div className="card budget-hero">
              <div className={`budget-verdict ${statusTone(total.status)}`}>
                <p className="budget-verdict-text">{statusSentence(t, total, locale, finished)}</p>
                <p className="muted small">
                  {[
                    !finished && paceText(t, total.pace_ratio),
                    !finished &&
                      (status.basis_months
                        ? t('budget.basis', { count: status.basis_months })
                        : t('budget.basisLinear')),
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              </div>

              <div className="budget-kpis">
                <div>
                  <span className="stat-label">{t('budget.spent')}</span>
                  <span className="stat-value">{formatMoney(total.spent, locale)}</span>
                  {total.flagged_spent > 0 && (
                    <span className="muted small">
                      {t('budget.flaggedIncluded', {
                        amount: formatMoney(total.flagged_spent, locale),
                      })}
                    </span>
                  )}
                </div>
                <div>
                  <span className="stat-label">{t('budget.budget')}</span>
                  <span className="stat-value">{total.budget !== null ? formatMoney(total.budget, locale) : '—'}</span>
                  {total.special_extra > 0 && total.base !== null && (
                    <span className="muted small">
                      {t('budget.baseplusExtra', {
                        base: formatMoney(total.base, locale),
                        extra: formatMoney(total.special_extra, locale),
                      })}
                    </span>
                  )}
                </div>
                {!finished && (
                  <div>
                    <span className="stat-label">{t('budget.projected')}</span>
                    <span className={`stat-value ${statusTone(total.status) === 'bad' ? 'expense' : ''}`}>
                      {formatMoney(total.projected, locale)}
                    </span>
                    {total.high > total.low && (
                      <span className="muted small">
                        {t('budget.range', {
                          low: formatCompactMoney(total.low, locale),
                          high: formatCompactMoney(total.high, locale),
                        })}
                      </span>
                    )}
                  </div>
                )}
                {!finished && total.daily_allowance !== null && (
                  <div>
                    <span className="stat-label">{t('budget.dailyAllowance')}</span>
                    <span className="stat-value">{formatMoney(total.daily_allowance, locale)}</span>
                    <span className="muted small">
                      {t('budget.daysLeft', {
                        count: status.days_in_month - status.elapsed_days,
                      })}
                    </span>
                  </div>
                )}
              </div>

              <BudgetBar line={total} />
              <BudgetChart
                path={total.path}
                elapsed={status.elapsed_days}
                budget={total.budget}
                low={total.low}
                high={total.high}
                locale={locale}
              />
              <div className="chart-legend">
                <span>
                  <i className="swatch budget-actual" /> {t('budget.legendActual')}
                </span>
                {!finished && (
                  <span>
                    <i className="swatch budget-forecast" /> {t('budget.legendForecast')}
                  </span>
                )}
                {total.budget !== null && (
                  <span>
                    <i className="swatch budget-limit" /> {t('budget.budget')}
                  </span>
                )}
              </div>

              {status.history.length > 0 && (
                <div className="budget-history">
                  <span className="stat-label">{t('budget.historyTitle')}</span>
                  <ul>
                    {status.history.map((h) => {
                      const ok = h.spent <= h.budget
                      const max = Math.max(...status.history.map((x) => Math.max(x.budget, x.spent)))
                      return (
                        <li key={h.year_month} title={`${formatMoney(h.spent, locale)} / ${formatMoney(h.budget, locale)}`}>
                          <button type="button" className="budget-history-bar" onClick={() => setYm(h.year_month)}>
                            <span
                              className={`fill ${ok ? 'ok' : 'bad'}`}
                              style={{ height: `${(h.spent / max) * 100}%` }}
                            />
                            <span className="limit" style={{ bottom: `${(h.budget / max) * 100}%` }} />
                          </button>
                          <span className="muted small">
                            {Number(h.year_month.slice(5))}
                            {t('budget.monthSuffix')}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
            </div>
          )}

          {(noBudget || showSetup) && (
            <div className="card">
              <div className="card-header">
                <h2>{t('budget.defaultsTitle')}</h2>
              </div>
              {noBudget && <p className="card-desc">{t('budget.emptyDesc')}</p>}
              <DefaultBudgetEditor
                defaults={defaults}
                onSaved={async () => {
                  await load()
                }}
              />
            </div>
          )}
        </div>
        <div>
          {status && status.categories.length > 0 && (
            <div className="card">
              <div className="card-header">
                <h2>{t('budget.categoriesTitle')}</h2>
              </div>
              <ul className="budget-cats">
                {status.categories.map((c) => {
                  return (
                    <li key={c.id}>
                      <div className="budget-cat-head">
                        <Link className="rank-link" to={`/transactions?ym=${ym}&category_id=${c.category_id}`}>
                          <span aria-hidden="true">{c.icon}</span> {c.name}
                        </Link>
                        <span className={`budget-chip ${statusTone(c.status)}`}>{t(`budget.level.${c.status}`)}</span>
                        <span className="spacer" />
                        <span className="mono">
                          {formatMoney(c.spent, locale)}
                          <span className="muted"> / {formatMoney(c.budget ?? 0, locale)}</span>
                        </span>
                      </div>
                      <BudgetBar line={c} compact />
                      {!finished && (
                        <span className="muted small">
                          {t('budget.catProjected', {
                            amount: formatMoney(c.projected, locale),
                          })}
                          {c.special_extra > 0 &&
                            ` · ${t('budget.includesExtra', { amount: formatMoney(c.special_extra, locale) })}`}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
              {status.unbudgeted_spent !== null && status.unbudgeted_spent > 0 && (
                <p className="hint">
                  {t('budget.unbudgeted', {
                    amount: formatMoney(status.unbudgeted_spent, locale),
                  })}
                </p>
              )}
            </div>
          )}

          <div className="card">
            <div className="card-header">
              <h2>{t('budget.specialsTitle')}</h2>
            </div>
            <p className="card-desc">{t('budget.specialsDesc')}</p>
            {status && status.specials.length === 0 && otherSpecials.length === 0 && (
              <p className="card-desc">{t('budget.specialsEmpty')}</p>
            )}
            <ul className="special-list">
              {status?.specials.map((s) => (
                <li key={s.id}>
                  <button type="button" className="special-item" onClick={() => setEditing(s)}>
                    <span className="special-icon" aria-hidden="true">
                      {KIND_ICON[s.kind]}
                    </span>
                    <span className="special-main">
                      <span className="special-name">
                        {s.name}{' '}
                        <span className={`budget-chip ${s.state === 'active' ? 'ok' : 'muted'}`}>
                          {t(`budget.state.${s.state}`)}
                        </span>
                      </span>
                      <span className="muted small">
                        {formatDateShort(s.date_from, locale)} – {formatDateShort(s.date_to, locale)}
                        {s.category_name && ` · ${s.category_icon ?? ''} ${s.category_name}`}
                        {s.allocated !== s.amount &&
                          ` · ${t('budget.allocated', { amount: formatMoney(s.allocated, locale) })}`}
                      </span>
                      <span className="special-progress">
                        <span
                          className={`fill ${s.spent > s.amount ? 'bad' : ''}`}
                          style={{
                            width: `${Math.min(100, (s.spent / s.amount) * 100)}%`,
                          }}
                        />
                      </span>
                    </span>
                    <span className="mono special-amount">
                      {formatMoney(s.spent, locale)}
                      <span className="muted"> / {formatMoney(s.amount, locale)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {otherSpecials.length > 0 && (
              <details className="special-others">
                <summary>{t('budget.otherSpecials', { count: otherSpecials.length })}</summary>
                <ul className="special-list">
                  {otherSpecials.map((s) => (
                    <li key={s.id}>
                      <button type="button" className="special-item" onClick={() => setEditing(s)}>
                        <span className="special-icon" aria-hidden="true">
                          {KIND_ICON[s.kind]}
                        </span>
                        <span className="special-main">
                          <span className="special-name">{s.name}</span>
                          <span className="muted small">
                            {formatDateShort(s.date_from, locale)} – {formatDateShort(s.date_to, locale)}
                          </span>
                        </span>
                        <span className="mono special-amount">{formatMoney(s.amount, locale)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        </div>
      </div>

      <Modal
        open={editing !== null}
        title={editing === 'new' ? t('budget.addSpecial') : t('budget.editSpecial')}
        onClose={() => setEditing(null)}
        size="wide"
      >
        {editing !== null && (
          <SpecialBudgetForm
            existing={editing === 'new' ? null : editing}
            onSaved={async () => {
              setEditing(null)
              await load()
            }}
            onCancel={() => setEditing(null)}
            onDelete={editing !== 'new' ? () => void removeSpecial(editing) : undefined}
          />
        )}
      </Modal>
    </>
  )
}
