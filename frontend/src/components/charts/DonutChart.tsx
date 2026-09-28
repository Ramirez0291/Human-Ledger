import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { CategoryBreakdown, CategoryGroup } from '../../api/client'
import { formatJPY, formatPercent } from '../../lib/format'

interface Props {
  data: CategoryBreakdown
  locale: string
  onDrill?: (group: CategoryGroup) => void
  onExclude?: (group: CategoryGroup) => void
}

const MAX_SLICES = 7
const SIZE = 200
const THICK = 24
const HOVER_GROW = 6
const R = SIZE / 2 - (THICK + HOVER_GROW) / 2 - 2

const FALLBACK = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7']

export interface Slice {
  key: string
  name: string
  icon: string | null
  color: string
  amount: number
  share: number
  count: number
  group: CategoryGroup | null
  isOther: boolean
}

export function buildSlices(data: CategoryBreakdown): Slice[] {
  const head = data.items.slice(0, MAX_SLICES)
  const tail = data.items.slice(MAX_SLICES)
  const slices: Slice[] = head.map((g, i) => ({
    key: g.key,
    name: g.name,
    icon: g.icon,
    color: g.color ?? FALLBACK[i % FALLBACK.length],
    amount: g.amount,
    share: g.share,
    count: g.count,
    group: g,
    isOther: false,
  }))
  const otherAmount = tail.reduce((n, g) => n + g.amount, 0) + data.uncategorized
  if (otherAmount > 0) {
    slices.push({
      key: '__other',
      name: '',
      icon: null,
      color: 'var(--border-strong)',
      amount: otherAmount,
      share: data.total ? otherAmount / data.total : 0,
      count: tail.reduce((n, g) => n + g.count, 0),
      group: null,
      isOther: true,
    })
  }
  return slices
}

export function DonutChart({ data, locale, onDrill, onExclude }: Props) {
  const { t } = useTranslation()
  const [hover, setHover] = useState<string | null>(null)
  const slices = useMemo(() => buildSlices(data), [data])

  if (!data.total) {
    return <p className="card-desc">{t('reports.noData')}</p>
  }

  const c = SIZE / 2
  const circumference = 2 * Math.PI * R
  let offset = 0
  const active = slices.find((s) => s.key === hover) ?? null
  const centerLabel = active ? active.name || t('reports.other') : t('reports.total')
  const centerValue = active ? active.amount : data.total

  return (
    <div className="donut">
      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={t('reports.categoryTitle')}
        onMouseLeave={() => setHover(null)}
      >
        <g transform={`rotate(-90 ${c} ${c})`}>
          {slices.map((s) => {
            const len = s.share * circumference
            const el = (
              <circle
                key={s.key}
                cx={c}
                cy={c}
                r={R}
                fill="none"
                stroke={s.color}
                strokeWidth={hover === s.key ? THICK + HOVER_GROW : THICK}
                strokeDasharray={`${Math.max(0, len - 2)} ${circumference - Math.max(0, len - 2)}`}
                strokeDashoffset={-offset - 1}
                className="donut-slice"
                onMouseEnter={() => setHover(s.key)}
                onClick={() => s.group && onDrill?.(s.group)}
                style={{ cursor: s.group && onDrill ? 'pointer' : 'default' }}
              />
            )
            offset += len
            return el
          })}
        </g>
        <text x={c} y={c - 6} textAnchor="middle" className="donut-center-label">
          {centerLabel}
        </text>
        <text x={c} y={c + 16} textAnchor="middle" className="donut-center-value">
          {formatJPY(centerValue, locale)}
        </text>
        {active && (
          <text x={c} y={c + 34} textAnchor="middle" className="donut-center-label">
            {formatPercent(active.share, locale)}
          </text>
        )}
      </svg>

      <ul className="donut-legend">
        {slices.map((s) => (
          <li
            key={s.key}
            className={hover === s.key ? 'active' : ''}
            onMouseEnter={() => setHover(s.key)}
            onMouseLeave={() => setHover(null)}
          >
            <button
              type="button"
              className="donut-legend-btn"
              disabled={!s.group || !onDrill}
              onFocus={() => setHover(s.key)}
              onBlur={() => setHover(null)}
              onClick={() => s.group && onDrill?.(s.group)}
            >
              <i className="swatch" style={{ background: s.color }} />
              <span className="donut-legend-name">
                {s.icon && <span aria-hidden="true">{s.icon} </span>}
                {s.isOther ? t('reports.other') : s.name}
              </span>
              <span className="mono donut-legend-amount">{formatJPY(s.amount, locale)}</span>
              <span className="muted donut-legend-share">{formatPercent(s.share, locale)}</span>
            </button>
            {onExclude && s.group && (
              <button
                type="button"
                className="donut-exclude"
                title={t('reports.excludeCategory', { name: s.name })}
                aria-label={t('reports.excludeCategory', { name: s.name })}
                onClick={() => s.group && onExclude(s.group)}
              >
                ⊘
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
