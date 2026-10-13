import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { BudgetStatus } from '../../api/client'
import { formatMoney } from '../../lib/format'
import { BudgetBar, KIND_ICON, paceText, statusSentence, statusTone } from './BudgetBits'

/**
 * 首页的预算卡：一句结论 + 总额进度 + 最需要留意的几个类目 + 正在进行的特别预算。
 * 没设预算时只给月底预测，并引导去设置。
 */
export function BudgetWidget({ status }: { status: BudgetStatus }) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const total = status.total
  const finished = status.elapsed_days >= status.days_in_month
  const watch = status.categories.filter((c) => c.status !== 'on_track').slice(0, 3)
  const active = status.specials.filter((s) => s.state === 'active')

  return (
    <div className="card budget-widget">
      <div className="card-header row">
        <h2>{t('nav.budget')}</h2>
        <span className="spacer" />
        <Link className="rank-link small" to="/budgets">
          {total.budget === null ? t('budget.setUp') : t('budget.viewAll')} →
        </Link>
      </div>
      <p className={`budget-verdict-text small-verdict ${statusTone(total.status)}`}>
        {statusSentence(t, total, locale, finished)}
      </p>
      {total.budget !== null && (
        <>
          <BudgetBar line={total} />
          <div className="budget-widget-meta muted small">
            <span>
              {formatMoney(total.spent, locale)} / {formatMoney(total.budget, locale)}
            </span>
            {!finished && total.daily_allowance !== null && (
              <span>
                {t('budget.dailyAllowanceShort', {
                  amount: formatMoney(total.daily_allowance, locale),
                })}
              </span>
            )}
            {!finished && paceText(t, total.pace_ratio) && <span>{paceText(t, total.pace_ratio)}</span>}
          </div>
        </>
      )}
      {watch.length > 0 && (
        <ul className="budget-watch">
          {watch.map((c) => (
            <li key={c.id}>
              <span>
                <span aria-hidden="true">{c.icon}</span> {c.name}
              </span>
              <span className={`budget-chip ${statusTone(c.status)}`}>{t(`budget.level.${c.status}`)}</span>
              <span className="mono small">
                {formatMoney(c.spent, locale)} / {formatMoney(c.budget ?? 0, locale)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {active.map((s) => (
        <p key={s.id} className="muted small budget-widget-special">
          {KIND_ICON[s.kind]} {s.name}：{formatMoney(s.spent, locale)} / {formatMoney(s.amount, locale)}
        </p>
      ))}
    </div>
  )
}
