import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatCompactMoney, formatMoney } from '../../lib/format'
import { niceScale, slotFromPointer } from './chartUtils'
import { useWidth } from './useWidth'

interface Props {
  /** 第 1..N 天末的累计：前 elapsed 天是实际，之后是预测 */
  path: number[]
  elapsed: number
  budget: number | null
  low: number
  high: number
  locale: string
  height?: number
}

const PAD = { top: 14, right: 12, bottom: 24, left: 48 }

/**
 * 本月累计支出 vs 预算。
 *
 * 实线是已经花的，虚线是按往常的逐日节奏推下去的；月底的扇形是预测区间（历史 25–75%）。
 * 虚线会在房租、订阅那几天跳一下——这正是按日历日学习历史的用意。
 */
export function BudgetChart({ path, elapsed, budget, low, high, locale, height = 200 }: Props) {
  const { t } = useTranslation()
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const n = path.length

  const layout = useMemo(() => {
    const innerW = Math.max(0, width - PAD.left - PAD.right)
    const innerH = height - PAD.top - PAD.bottom
    const scale = niceScale(Math.max(budget ?? 0, high, ...path))
    const y = (v: number) => PAD.top + ((scale.top - v) / (scale.top - scale.bottom)) * innerH
    const slot = n ? innerW / n : 0
    return { innerW, innerH, y, slot, ticks: scale.values }
  }, [width, height, budget, high, path, n])

  if (!n) return null
  const { y, slot, innerW, innerH, ticks } = layout
  const x = (i: number) => PAD.left + slot * i + slot / 2
  const d = Math.min(elapsed, n)
  const line = (from: number, to: number) =>
    path
      .slice(from, to)
      .map((v, k) => `${k ? 'L' : 'M'}${x(from + k)},${y(v)}`)
      .join(' ')
  // 预测从「今天」的实际点接出去；月初还没花钱时从 0 起
  const forecastFrom = d > 0 ? d - 1 : 0
  const fan =
    d < n ? `M${x(forecastFrom)},${y(d > 0 ? path[d - 1] : 0)} L${x(n - 1)},${y(high)} L${x(n - 1)},${y(low)} Z` : null
  const over = budget !== null && path[n - 1] > budget
  const focus = hover !== null ? hover : null

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={t('budget.chartLabel')} className="chart-svg">
          {ticks.map((v) => (
            <g key={v}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={y(v)}
                y2={y(v)}
                className={v === 0 ? 'chart-baseline' : 'chart-grid'}
              />
              <text x={PAD.left - 6} y={y(v) + 4} className="chart-tick" textAnchor="end">
                {formatCompactMoney(v, locale)}
              </text>
            </g>
          ))}

          {fan && <path d={fan} className={`budget-fan ${over ? 'over' : ''}`} />}

          {budget !== null && (
            <g className="chart-avg budget-line">
              <line x1={PAD.left} x2={width - PAD.right} y1={y(budget)} y2={y(budget)} />
              <text x={PAD.left + 4} y={y(budget) - 4}>
                {t('budget.budgetLine', {
                  amount: formatCompactMoney(budget, locale),
                })}
              </text>
            </g>
          )}

          {d > 0 && <path className="chart-line budget-actual" d={line(0, d)} />}
          {d < n && <path className={`chart-line budget-forecast ${over ? 'over' : ''}`} d={line(forecastFrom, n)} />}
          {d > 0 && d < n && <circle cx={x(d - 1)} cy={y(path[d - 1])} r={4} className="chart-marker budget-now" />}

          {[1, 5, 10, 15, 20, 25, n].map((day) =>
            day <= n ? (
              <text key={day} x={x(day - 1)} y={height - 6} textAnchor="middle" className="chart-tick">
                {day}
              </text>
            ) : null,
          )}

          {focus !== null && (
            <line x1={x(focus)} x2={x(focus)} y1={PAD.top} y2={height - PAD.bottom} className="chart-crosshair" />
          )}

          <rect
            x={PAD.left}
            y={PAD.top}
            width={innerW}
            height={innerH}
            fill="transparent"
            style={{ touchAction: 'pan-y' }}
            onPointerMove={(e) => setHover(slotFromPointer(e, PAD.left, slot, n))}
            onPointerDown={(e) => setHover(slotFromPointer(e, PAD.left, slot, n))}
            onPointerLeave={() => setHover(null)}
          />
        </svg>
      )}

      {focus !== null && (
        <div
          className="chart-tooltip"
          style={{
            left: Math.min(Math.max(x(focus), 90), Math.max(width - 90, 90)),
          }}
        >
          <strong>{t('budget.dayN', { day: focus + 1 })}</strong>
          <span>
            {t(focus < d ? 'budget.actualCum' : 'budget.forecastCum')}
            <b>{formatMoney(path[focus], locale)}</b>
          </span>
          {budget !== null && (
            <em className={path[focus] > budget ? 'bad' : 'good'}>
              {t(path[focus] > budget ? 'budget.overBy' : 'budget.leftBy', {
                amount: formatMoney(Math.abs(budget - path[focus]), locale),
              })}
            </em>
          )}
        </div>
      )}
    </div>
  )
}
