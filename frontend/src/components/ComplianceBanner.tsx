import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { Compliance } from '../api/client'
import { formatMoney, formatPercent } from '../lib/format'

/** 等级 3 以上轮播的监察口吻台词，4 秒换一句 */
const QUIPS = 5

/**
 * 合规模式的账面状态条（吸顶玻璃的最下沿）。
 *
 * 0 级只是一枚安静的「账实相符」徽章；1 级起变成横幅，措辞与配色逐级升级，
 * 3 级以上轮播监察台词，整页的暗角与脉冲由 budget.css 里的 [data-tension] 负责。
 */
export function ComplianceBanner({ data }: { data: Compliance }) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const [quip, setQuip] = useState(0)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (data.level < 3) return
    const timer = setInterval(() => setQuip((q) => (q + 1) % QUIPS), 4000)
    return () => clearInterval(timer)
  }, [data.level])

  if (data.level === 0) {
    return (
      <div className="compliance-bar calm" role="status">
        <span className="compliance-seal">✓</span> {t('compliance.calm')}
      </div>
    )
  }

  const amount = formatMoney(data.total_abs_diff, locale)
  const pct = formatPercent(data.ratio, locale)
  const headline =
    data.total_abs_diff === 0
      ? t('compliance.gapsOnly', { count: data.gaps })
      : t(`compliance.level${data.level}`, { amount, pct })
  const problems = data.accounts.filter((a) => a.status !== 'ok')

  return (
    <div className={`compliance-bar level-${data.level}`} role={data.level >= 3 ? 'alert' : 'status'}>
      <div className="compliance-main">
        <span className="compliance-badge">{t(`compliance.badge${data.level}`)}</span>
        <span className="compliance-headline">{headline}</span>
        {data.level >= 3 && (
          <span key={quip} className="compliance-quip">
            {t(`compliance.quip${quip}`)}
          </span>
        )}
        <span className="spacer" />
        <button type="button" className="compliance-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {t(open ? 'compliance.hide' : 'compliance.details', { count: problems.length })}
        </button>
        <Link className="compliance-action" to="/accounts">
          {t('compliance.goReconcile')}
        </Link>
      </div>
      {open && (
        <ul className="compliance-list">
          {problems.map((a) => (
            <li key={a.account_id}>
              <span className="compliance-account">{a.name}</span>
              <span className={`compliance-stamp ${a.status}`}>{t(`compliance.status.${a.status}`)}</span>
              {a.status === 'diff' && <span className="mono">{formatMoney(a.diff, locale)}</span>}
              {a.status === 'stale' && a.days !== null && (
                <span className="muted small">{t('compliance.daysAgo', { count: a.days })}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
