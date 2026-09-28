import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import {
  api,
  type CategoryGroup,
  type DailyReport,
  type LargeExpense,
  type ReportFilters,
  type ReportOverview,
  type Transaction,
  type TrendMonth,
} from '../api/client'
import { DailyChart } from '../components/charts/DailyChart'
import { DonutChart } from '../components/charts/DonutChart'
import { TrendChart } from '../components/charts/TrendChart'
import { Icon } from '../components/Icon'
import { useLedger } from '../context/LedgerContext'
import {
  currentYearMonth,
  formatDateShort,
  formatJPY,
  formatPercent,
  formatSigned,
  formatYearMonth,
  monthRange,
  shiftYearMonth,
  todayISO,
} from '../lib/format'

const TREND_MONTHS = 12
const THRESHOLDS = [10000, 30000, 50000, 100000]
const STORAGE_KEY = 'reports.analysis.v1'

/** 分析口径：哪些开支不算进「日常开支」。按浏览器记住，下次打开还是这套 */
interface Analysis {
  excludeFlagged: boolean
  maxSingle: number | null
  excludeCategories: number[]
}

const DEFAULT_ANALYSIS: Analysis = { excludeFlagged: true, maxSingle: null, excludeCategories: [] }

function loadAnalysis(): Analysis {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...DEFAULT_ANALYSIS, ...(JSON.parse(raw) as Partial<Analysis>) }
  } catch {
    /* 隐私模式等拿不到存储时用默认值 */
  }
  return DEFAULT_ANALYSIS
}

export function ReportsPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const navigate = useNavigate()
  const { accounts, categories, categoryById, refreshAccounts } = useLedger()

  const [ym, setYm] = useState(currentYearMonth())
  const [accountId, setAccountId] = useState<number | ''>('')
  const [categoryId, setCategoryId] = useState<number | ''>('')
  const [query, setQuery] = useState('')
  const [side, setSide] = useState<'expense' | 'income'>('expense')
  const [drill, setDrill] = useState<CategoryGroup | null>(null)
  const [analysis, setAnalysis] = useState<Analysis>(loadAnalysis)
  const [customThreshold, setCustomThreshold] = useState('')
  const [selectedDay, setSelectedDay] = useState<number | null>(null)

  const [overview, setOverview] = useState<ReportOverview | null>(null)
  const [trend, setTrend] = useState<TrendMonth[]>([])
  const [daily, setDaily] = useState<DailyReport | null>(null)
  const [large, setLarge] = useState<LargeExpense[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(analysis))
    } catch {
      /* 同上 */
    }
  }, [analysis])

  const filters = useMemo<ReportFilters>(() => {
    const f: ReportFilters = {}
    if (accountId !== '') f.account_id = accountId
    if (categoryId !== '') f.category_id = categoryId
    if (query.trim()) f.q = query.trim()
    if (!analysis.excludeFlagged) f.include_flagged = true
    if (analysis.maxSingle !== null) f.max_single = analysis.maxSingle
    if (analysis.excludeCategories.length) f.exclude_categories = analysis.excludeCategories.join(',')
    return f
  }, [accountId, categoryId, query, analysis])

  const load = useCallback(async () => {
    setError('')
    setLoading(true)
    try {
      const [o, tr, d, l] = await Promise.all([
        api.reportOverview(ym, filters),
        api.reportTrend(ym, TREND_MONTHS, filters),
        api.reportDaily(ym, filters),
        api.reportLargeExpenses(ym, filters),
      ])
      setOverview(o)
      setTrend(tr.months)
      setDaily(d)
      setLarge(l.items)
    } catch {
      setError(t('common.error'))
    } finally {
      setLoading(false)
    }
  }, [ym, filters, t])

  useEffect(() => {
    const timer = setTimeout(() => void load(), query ? 300 : 0)
    return () => clearTimeout(timer)
  }, [load, query])

  // 月份或筛选一变，下钻与选中的日期就失效
  useEffect(() => {
    setDrill(null)
  }, [ym, filters, side])
  useEffect(() => {
    setSelectedDay(null)
  }, [ym])

  const flatCategories = useMemo(() => categories.flatMap((c) => [c, ...c.children]), [categories])

  const exportHref = useMemo(() => {
    const { from, to } = monthRange(ym)
    return api.exportUrl({
      date_from: from,
      date_to: to,
      account_id: filters.account_id,
      category_id: filters.category_id,
      q: filters.q,
    })
  }, [ym, filters])

  async function toggleExclude(id: number, value: boolean) {
    await api.setExcludeFromAnalysis(id, value)
    await load()
  }

  async function convertToTransfer(id: number, counterpartId: number) {
    await api.convertToTransfer(id, counterpartId)
    await Promise.all([load(), refreshAccounts()])
  }

  function excludeCategory(g: CategoryGroup) {
    setAnalysis((a) =>
      a.excludeCategories.includes(g.category_id)
        ? a
        : { ...a, excludeCategories: [...a.excludeCategories, g.category_id] },
    )
  }

  const analysisIsDefault =
    analysis.excludeFlagged && analysis.maxSingle === null && analysis.excludeCategories.length === 0
  const excludingSomething = !!overview && overview.excluded.count > 0

  const breakdown = overview ? (side === 'expense' ? overview.expense_by_category : overview.income_by_category) : null
  const maxMerchant = overview?.top_merchants[0]?.amount ?? 0
  const isCurrentMonth = ym === currentYearMonth()
  const today = isCurrentMonth ? Number(todayISO().slice(8, 10)) : null

  return (
    <>
      <div className="page-head">
        <div className="month-nav">
          <button className="btn-ghost btn-icon" aria-label={t('common.prevMonth')} onClick={() => setYm(shiftYearMonth(ym, -1))}>
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
          {!isCurrentMonth && (
            <button className="btn-ghost small" onClick={() => setYm(currentYearMonth())}>
              {t('reports.thisMonth')}
            </button>
          )}
        </div>
        <div className="page-actions">
          {loading && <span className="muted small">{t('common.loading')}</span>}
          <a className="btn-ghost link-btn-inline" href={exportHref} download>
            {t('reports.exportCsv')}
          </a>
        </div>
      </div>

      <div className="card filter-bar">
        <input
          type="search"
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
        <select value={categoryId} onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">{t('txn.allCategories')}</option>
          {flatCategories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.parent_id ? '　' : ''}
              {c.name}
            </option>
          ))}
        </select>

        {/* ---- 分析口径：主动除外大额 / 意外开支 ---- */}
        <div className="analysis-bar">
          <span className="analysis-label">{t('reports.analysisLabel')}</span>
          <button
            type="button"
            className={`chip ${analysis.excludeFlagged ? 'on' : ''}`}
            aria-pressed={analysis.excludeFlagged}
            title={t('reports.excludeFlaggedHint')}
            onClick={() => setAnalysis((a) => ({ ...a, excludeFlagged: !a.excludeFlagged }))}
          >
            {t('reports.excludeFlagged')}
          </button>

          <span className="analysis-sep" aria-hidden="true" />
          <span className="muted small">{t('reports.maxSingle')}</span>
          <button
            type="button"
            className={`chip ${analysis.maxSingle === null ? 'on' : ''}`}
            aria-pressed={analysis.maxSingle === null}
            onClick={() => setAnalysis((a) => ({ ...a, maxSingle: null }))}
          >
            {t('reports.noLimit')}
          </button>
          {THRESHOLDS.map((v) => (
            <button
              key={v}
              type="button"
              className={`chip ${analysis.maxSingle === v ? 'on' : ''}`}
              aria-pressed={analysis.maxSingle === v}
              onClick={() => setAnalysis((a) => ({ ...a, maxSingle: v }))}
            >
              ≤ {formatJPY(v, locale)}
            </button>
          ))}
          <form
            className="chip-input"
            onSubmit={(e) => {
              e.preventDefault()
              const n = Number(customThreshold.replace(/[^\d]/g, ''))
              if (n > 0) setAnalysis((a) => ({ ...a, maxSingle: n }))
            }}
          >
            <input
              inputMode="numeric"
              placeholder={t('reports.customLimit')}
              value={customThreshold}
              onChange={(e) => setCustomThreshold(e.target.value)}
              aria-label={t('reports.customLimit')}
            />
          </form>

          {analysis.excludeCategories.map((id) => (
            <span key={id} className="chip on removable">
              ⊘ {categoryById.get(id)?.name ?? id}
              <button
                type="button"
                aria-label={t('common.delete')}
                onClick={() =>
                  setAnalysis((a) => ({ ...a, excludeCategories: a.excludeCategories.filter((x) => x !== id) }))
                }
              >
                ×
              </button>
            </span>
          ))}

          {!analysisIsDefault && (
            <button type="button" className="btn-ghost small" onClick={() => setAnalysis(DEFAULT_ANALYSIS)}>
              {t('reports.resetAnalysis')}
            </button>
          )}
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      {overview && (
        <>
          {excludingSomething && (
            <div className="analysis-notice">
              {t('reports.excludedNotice', {
                amount: formatJPY(overview.excluded.expense, locale),
                count: overview.excluded.count,
                raw: formatJPY(overview.raw_totals.expense, locale),
              })}
            </div>
          )}

          <div className="stat-row">
            <Kpi
              label={excludingSomething ? t('reports.ordinaryExpense') : t('reports.expense')}
              value={overview.totals.expense}
              prev={overview.previous.expense}
              cls="expense"
              locale={locale}
              lowerIsBetter
            />
            <Kpi
              label={t('reports.income')}
              value={overview.totals.income}
              prev={overview.previous.income}
              cls="income"
              locale={locale}
            />
            <Kpi
              label={t('reports.net')}
              value={overview.totals.net}
              prev={overview.previous.net}
              cls={overview.totals.net >= 0 ? 'income' : 'expense'}
              locale={locale}
            />
          </div>

          <div className="card">
            <div className="card-header">
              <h2>{t('reports.trendTitle')}</h2>
              <span className="muted">{t('reports.trendHint', { count: TREND_MONTHS })}</span>
            </div>
            <TrendChart months={trend} locale={locale} activeMonth={ym} onPickMonth={setYm} />
          </div>

          {daily && (
            <div className="card">
              <div className="card-header">
                <h2>{t('reports.dailyTitle')}</h2>
                <span className="muted">{t('reports.dailyHint')}</span>
              </div>
              <DailyChart
                data={daily}
                locale={locale}
                today={today}
                selectedDay={selectedDay}
                onPickDay={setSelectedDay}
              />
              {selectedDay !== null && (
                <DayPanel
                  date={`${ym}-${String(selectedDay).padStart(2, '0')}`}
                  filters={filters}
                  locale={locale}
                  onToggle={toggleExclude}
                  onClose={() => setSelectedDay(null)}
                />
              )}
            </div>
          )}

          <div className="report-grid">
            <div className="card">
              <div className="card-header">
                <h2>{t('reports.categoryTitle')}</h2>
                <div className="segmented source-toggle" role="group">
                  <button type="button" aria-pressed={side === 'expense'} onClick={() => setSide('expense')}>
                    {t('reports.expense')}
                  </button>
                  <button type="button" aria-pressed={side === 'income'} onClick={() => setSide('income')}>
                    {t('reports.income')}
                  </button>
                </div>
              </div>

              {breakdown && !drill && (
                <DonutChart
                  data={breakdown}
                  locale={locale}
                  onDrill={setDrill}
                  onExclude={side === 'expense' ? excludeCategory : undefined}
                />
              )}

              {drill && (
                <div className="drill">
                  <button className="btn-ghost drill-back" onClick={() => setDrill(null)}>
                    <Icon name="chevronLeft" size={14} /> {t('reports.backToAll')}
                  </button>
                  <div className="drill-head">
                    <span className="drill-name">
                      {drill.icon && <span aria-hidden="true">{drill.icon} </span>}
                      {drill.name}
                    </span>
                    <span className="mono">{formatJPY(drill.amount, locale)}</span>
                    <span className="muted">{formatPercent(drill.share, locale)}</span>
                  </div>
                  <ul className="rank-list">
                    {drill.children.map((c) => (
                      <li key={c.category_id}>
                        <Link
                          className="rank-name rank-link"
                          to={`/transactions?ym=${ym}&category_id=${c.category_id}`}
                        >
                          {c.icon && <span aria-hidden="true">{c.icon} </span>}
                          {c.category_id === drill.category_id ? t('reports.directOnParent') : c.name}
                          <span className="muted"> · {t('reports.txnCount', { count: c.count })}</span>
                        </Link>
                        <span className="rank-bar">
                          <span style={{ width: `${c.share * 100}%`, background: drill.color ?? 'var(--accent)' }} />
                        </span>
                        <span className="mono rank-amount">{formatJPY(c.amount, locale)}</span>
                        <span className="muted rank-share">{formatPercent(c.share, locale)}</span>
                      </li>
                    ))}
                  </ul>
                  <Link className="hint" to={`/transactions?ym=${ym}&category_id=${drill.category_id}`}>
                    {t('reports.viewTransactions')} ›
                  </Link>
                </div>
              )}

              {breakdown && breakdown.uncategorized > 0 && !drill && (
                <p className="hint" style={{ marginTop: 12 }}>
                  {t('reports.uncategorized', { amount: formatJPY(breakdown.uncategorized, locale) })}
                </p>
              )}
              {side === 'expense' && !drill && breakdown && breakdown.total > 0 && (
                <p className="hint">{t('reports.excludeCategoryHint')}</p>
              )}
            </div>

            <div className="card">
              <div className="card-header">
                <h2>{t('reports.largeTitle')}</h2>
              </div>
              <p className="card-desc">{t('reports.largeDesc')}</p>
              {large.length === 0 ? (
                <p className="card-desc">{t('reports.noData')}</p>
              ) : (
                <ul className="large-list">
                  {large.map((e) => {
                    const excluded = e.exclude_from_analysis || e.over_threshold
                    return (
                      <li key={e.id} className={excluded ? 'excluded' : ''}>
                        <div className="large-main">
                          <span className="large-merchant" title={e.merchant}>
                            {e.merchant || t('txn.noMerchant')}
                          </span>
                          <span className="muted small">
                            {formatDateShort(e.date, locale)}
                            {e.category_name && ` · ${e.category_icon ?? ''} ${e.category_name}`}
                            {e.over_threshold && !e.exclude_from_analysis && ` · ${t('reports.overThreshold')}`}
                          </span>
                        </div>
                        <span className="mono large-amount">{formatJPY(e.amount, locale)}</span>
                        <ExcludeSwitch
                          excluded={e.exclude_from_analysis}
                          onChange={(v) => void toggleExclude(e.id, v)}
                        />
                        {e.transfer_like && (
                          <TransferFix
                            item={e}
                            accounts={accounts.filter((a) => a.id !== e.account_id && !a.is_archived)}
                            onConvert={(to) => convertToTransfer(e.id, to)}
                          />
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <h2>{t('reports.merchantsTitle')}</h2>
              <span className="muted">{t('reports.merchantsHint')}</span>
            </div>
            {overview.top_merchants.length === 0 ? (
              <p className="card-desc">{t('reports.noData')}</p>
            ) : (
              <ol className="rank-list numbered">
                {overview.top_merchants.map((m, i) => (
                  <li
                    key={m.merchant_norm}
                    className="clickable"
                    tabIndex={0}
                    onClick={() => navigate(`/transactions?ym=${ym}&q=${encodeURIComponent(m.merchant)}`)}
                    onKeyDown={(e) =>
                      e.key === 'Enter' && navigate(`/transactions?ym=${ym}&q=${encodeURIComponent(m.merchant)}`)
                    }
                  >
                    <span className="rank-no">{i + 1}</span>
                    <span className="rank-name" title={m.merchant}>
                      {m.merchant}
                      <span className="muted"> · {t('reports.txnCount', { count: m.count })}</span>
                    </span>
                    <span className="rank-bar">
                      <span style={{ width: `${maxMerchant ? (m.amount / maxMerchant) * 100 : 0}%` }} />
                    </span>
                    <span className="mono rank-amount">{formatJPY(m.amount, locale)}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div className="card">
            <div className="card-header">
              <h2>{t('reports.accountsTitle')}</h2>
            </div>
            <div className="table-scroll">
              <table className="report-table">
                <thead>
                  <tr>
                    <th>{t('form.account')}</th>
                    <th className="num">{t('reports.balance')}</th>
                    <th className="num">{t('reports.monthIncome')}</th>
                    <th className="num">{t('reports.monthExpense')}</th>
                    <th className="num">{t('reports.monthDelta')}</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.accounts.map((a) => (
                    <tr
                      key={a.id}
                      className="clickable"
                      onClick={() => navigate(`/transactions?ym=${ym}&account_id=${a.id}`)}
                    >
                      <td>
                        <span className="dot" style={{ background: a.color ?? 'var(--border-strong)' }} />
                        {a.name}
                      </td>
                      <td className={`num mono ${a.balance < 0 ? 'expense' : ''}`}>{formatJPY(a.balance, locale)}</td>
                      <td className="num mono">{a.month_income ? formatJPY(a.month_income, locale) : '—'}</td>
                      <td className="num mono">{a.month_expense ? formatJPY(a.month_expense, locale) : '—'}</td>
                      <td className={`num mono ${a.month_delta < 0 ? 'expense' : a.month_delta > 0 ? 'income' : ''}`}>
                        {a.month_delta ? formatSigned(a.month_delta, locale) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint" style={{ marginTop: 8 }}>
              {t('reports.accountsHint')}
            </p>
          </div>
        </>
      )}
    </>
  )
}

// --------------------------------------------------------------------------

/** 「计入 / 除外」开关。开 = 计入分析 */
function ExcludeSwitch({ excluded, onChange }: { excluded: boolean; onChange: (excluded: boolean) => void }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      role="switch"
      aria-checked={!excluded}
      className={`switch ${excluded ? '' : 'on'}`}
      title={excluded ? t('reports.switchIncludeHint') : t('reports.switchExcludeHint')}
      onClick={(e) => {
        e.stopPropagation()
        onChange(!excluded)
      }}
    >
      <span className="switch-track">
        <span className="switch-thumb" />
      </span>
      <span className="switch-label">{excluded ? t('reports.excludedShort') : t('reports.includedShort')}</span>
    </button>
  )
}

/** 选中某天后列出当天的支出，可逐笔除外 */
function DayPanel({
  date,
  filters,
  locale,
  onToggle,
  onClose,
}: {
  date: string
  filters: ReportFilters
  locale: string
  onToggle: (id: number, value: boolean) => Promise<void>
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [items, setItems] = useState<Transaction[] | null>(null)

  const load = useCallback(async () => {
    const page = await api.transactions({
      date_from: date,
      date_to: date,
      direction: 'expense',
      account_id: filters.account_id,
      category_id: filters.category_id,
      q: filters.q,
      page_size: 100,
    })
    setItems(page.items)
  }, [date, filters.account_id, filters.category_id, filters.q])

  useEffect(() => {
    setItems(null)
    void load()
  }, [load])

  return (
    <div className="day-panel">
      <div className="day-panel-head">
        <strong>
          {new Intl.DateTimeFormat(locale, { month: 'long', day: 'numeric', weekday: 'short' }).format(
            new Date(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10))),
          )}
        </strong>
        <span className="spacer" />
        <Link className="hint" to={`/transactions?ym=${date.slice(0, 7)}`}>
          {t('reports.viewTransactions')} ›
        </Link>
        <button className="btn-ghost btn-icon" aria-label={t('common.close')} onClick={onClose}>
          <Icon name="close" size={14} />
        </button>
      </div>
      {items === null ? (
        <p className="muted small">{t('common.loading')}</p>
      ) : items.length === 0 ? (
        <p className="muted small">{t('reports.dayEmpty')}</p>
      ) : (
        <ul className="large-list">
          {items.map((x) => (
            <li key={x.id} className={x.exclude_from_analysis ? 'excluded' : ''}>
              <div className="large-main">
                <span className="large-merchant">{x.merchant_raw || t('txn.noMerchant')}</span>
                <span className="muted small">
                  {x.account_name}
                  {x.category_name && ` · ${x.category_name}`}
                </span>
              </div>
              <span className="mono large-amount">{formatJPY(x.amount, locale)}</span>
              <ExcludeSwitch
                excluded={x.exclude_from_analysis}
                onChange={async (v) => {
                  await onToggle(x.id, v)
                  await load()
                }}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Kpi({
  label,
  value,
  prev,
  cls,
  locale,
  lowerIsBetter = false,
}: {
  label: string
  value: number
  prev: number
  cls: string
  locale: string
  lowerIsBetter?: boolean
}) {
  const { t } = useTranslation()
  const diff = value - prev
  const good = diff === 0 ? null : lowerIsBetter ? diff < 0 : diff > 0
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${cls}`}>{formatJPY(value, locale)}</span>
      <span className={`stat-delta ${good === null ? '' : good ? 'good' : 'bad'}`}>
        {diff === 0 ? (
          t('reports.sameAsPrev')
        ) : (
          <>
            {diff > 0 ? '▲' : '▼'} {formatJPY(Math.abs(diff), locale)}
            {prev !== 0 && <span className="muted"> ({formatPercent(Math.abs(diff) / Math.abs(prev), locale)})</span>}
            <span className="muted"> {t('reports.vsPrev')}</span>
          </>
        )}
      </span>
    </div>
  )
}

/**
 * 大额支出里像「钱换了个账户」的那几笔：信用卡还款、ATM 取现、充值、转入证券。
 * 卡上的每笔消费已经各记一次，还款再算支出就是双计，所以给一个就地改记转账的入口。
 */
function TransferFix({
  item,
  accounts,
  onConvert,
}: {
  item: LargeExpense
  accounts: { id: number; name: string }[]
  onConvert: (counterpartId: number) => Promise<void>
}) {
  const { t } = useTranslation()
  const [to, setTo] = useState<number | ''>(item.suggested_counterpart_id ?? '')
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(item.suggested_counterpart_id !== null)

  if (!accounts.length) return null
  if (!open) {
    return (
      <div className="transfer-fix">
        <span className="muted">{t('reports.transferLike')}</span>
        <button type="button" className="btn-link" onClick={() => setOpen(true)}>
          {t('reports.transferFixOpen')}
        </button>
      </div>
    )
  }
  return (
    <div className="transfer-fix">
      <span className="muted">{t('reports.transferLike')}</span>
      <span className="transfer-fix-form">
        <span className="muted">{item.account_name} →</span>
        <select value={to} onChange={(e) => setTo(e.target.value ? Number(e.target.value) : '')} aria-label={t('reports.transferTo')}>
          <option value="">{t('reports.transferTo')}</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn-ghost small"
          disabled={to === '' || busy}
          onClick={async () => {
            if (to === '') return
            setBusy(true)
            try {
              await onConvert(to)
            } finally {
              setBusy(false)
            }
          }}
        >
          {t('reports.transferFix')}
        </button>
      </span>
    </div>
  )
}
