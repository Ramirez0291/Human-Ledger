import { useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TrendMonth } from '../../api/client'
import { formatCompactYen, formatJPY } from '../../lib/format'
import { BarPath, HatchPattern, niceScale, slotFromPointer } from './chartUtils'
import { useWidth } from './useWidth'

interface Props {
  months: TrendMonth[]
  locale: string
  /** 高亮的月份（当前查看的月） */
  activeMonth?: string
  onPickMonth?: (ym: string) => void
}

type Series = 'income' | 'expense' | 'excluded' | 'net' | 'avg'

const HEIGHT = 260
const PAD = { top: 16, right: 8, bottom: 28, left: 48 }
const GAP = 2 // 相邻柱之间留 2px 底色缝

/**
 * 近 N 个月收支柱状图 + 结余折线 + 月均支出参考线。
 *
 * 三条序列共用一根日元轴，不做双轴。结余可能为负，所以零线不一定在底部。
 * 被除外的支出（大额 / 意外开支）叠在支出柱顶上，用斜纹画，默认显示但不计入月均。
 *
 * 交互：
 * - 图例可点，开关各序列；纵轴随可见序列重算，关掉收入后支出的起伏才看得清
 * - 指针 / 手指在图上移动即出十字线与数值；点一下切换到该月
 * - 图表可聚焦，←→ 移动、Enter 选中，Esc 退出
 */
export function TrendChart({ months, locale, activeMonth, onPickMonth }: Props) {
  const { t } = useTranslation()
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const [hidden, setHidden] = useState<Set<Series>>(new Set())
  const hatchId = `hatch-${useId().replace(/:/g, '')}`
  // 触屏上第一次点只看数值，再点同一列才切换月份；鼠标直接切换
  const tap = useRef<{ type: string; prev: number | null }>({ type: 'mouse', prev: null })

  const on = (s: Series) => !hidden.has(s)
  const toggle = (s: Series) =>
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })

  // 月均只统计有记录的月份：空月（还没开始记账）拉低均值没有意义
  const average = useMemo(() => {
    const active = months.filter((m) => m.expense > 0 || m.income > 0)
    return active.length ? Math.round(active.reduce((n, m) => n + m.expense, 0) / active.length) : 0
  }, [months])
  const hasExcluded = months.some((m) => m.excluded_expense > 0)

  const layout = useMemo(() => {
    const innerW = Math.max(0, width - PAD.left - PAD.right)
    const innerH = HEIGHT - PAD.top - PAD.bottom
    const candidates: number[] = []
    for (const m of months) {
      if (on('income')) candidates.push(m.income)
      if (on('expense')) candidates.push(m.expense + (on('excluded') ? m.excluded_expense : 0))
      if (on('net')) candidates.push(m.net)
    }
    if (on('avg')) candidates.push(average)
    const minNet = on('net') ? Math.min(0, ...months.map((m) => m.net)) : 0
    const scale = niceScale(Math.max(0, ...candidates), minNet)
    const y = (v: number) => PAD.top + ((scale.top - v) / (scale.top - scale.bottom)) * innerH
    const slot = months.length ? innerW / months.length : 0
    const bars = (on('income') ? 1 : 0) + (on('expense') ? 1 : 0)
    const barW = bars ? Math.max(3, Math.min(24, (slot - GAP * 3) / bars)) : 0
    return { innerW, innerH, y, slot, barW, bars, ticks: scale.values }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [months, width, hidden, average])

  if (!months.length) return null

  const { y, slot, barW, bars, ticks, innerH } = layout
  const xCenter = (i: number) => PAD.left + slot * i + slot / 2
  const zero = y(0)
  const hovered = hover !== null ? months[hover] : null
  // 窄屏上月份标签隔一个显示
  const labelEvery = slot < 34 ? 2 : 1

  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const cur = hover ?? months.findIndex((m) => m.month === activeMonth)
      const next = Math.min(months.length - 1, Math.max(0, cur + (e.key === 'ArrowRight' ? 1 : -1)))
      setHover(next)
    } else if (e.key === 'Enter' && hover !== null) {
      onPickMonth?.(months[hover].month)
    } else if (e.key === 'Escape') {
      setHover(null)
    }
  }

  const legend: { key: Series; label: string; cls: string; show: boolean }[] = [
    { key: 'income', label: t('reports.income'), cls: 'income', show: true },
    { key: 'expense', label: t('reports.expense'), cls: 'expense', show: true },
    { key: 'excluded', label: t('reports.excludedSeries'), cls: 'excluded', show: hasExcluded },
    { key: 'net', label: t('reports.net'), cls: 'net', show: true },
    { key: 'avg', label: t('reports.avgExpense', { amount: formatCompactYen(average, locale) }), cls: 'avg', show: average > 0 },
  ]

  return (
    <div className="chart" ref={ref}>
      <div className="chart-legend interactive" role="group" aria-label={t('reports.legendHint')}>
        {legend
          .filter((l) => l.show)
          .map((l) => (
            <button
              key={l.key}
              type="button"
              className={`legend-item ${on(l.key) ? '' : 'off'}`}
              aria-pressed={on(l.key)}
              onClick={() => toggle(l.key)}
            >
              <i className={`swatch ${l.cls}`} /> {l.label}
            </button>
          ))}
      </div>

      {width > 0 && (
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={t('reports.trendTitle')}
          tabIndex={0}
          className="chart-svg"
          onKeyDown={onKey}
          onBlur={() => setHover(null)}
        >
          <defs>
            <HatchPattern id={hatchId} className="hatch-expense" />
          </defs>

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
                {formatCompactYen(v, locale)}
              </text>
            </g>
          ))}

          {months.map((m, i) => {
            const cx = xCenter(i)
            const active = m.month === activeMonth
            const left = cx - (barW * bars + GAP * (bars - 1)) / 2
            const expX = on('income') ? left + barW + GAP : left
            const expTop = y(m.expense)
            return (
              <g key={m.month} className={`chart-slot ${active ? 'active' : ''} ${hover === i ? 'hover' : ''}`}>
                <rect x={PAD.left + slot * i} y={PAD.top} width={slot} height={innerH} className="chart-hit" />
                {on('income') && (
                  <BarPath x={left} y0={zero} y1={y(m.income)} w={barW} className="chart-bar income" />
                )}
                {on('expense') && (
                  <>
                    <BarPath
                      x={expX}
                      y0={zero}
                      y1={expTop}
                      w={barW}
                      className="chart-bar expense"
                      roundTop={!(on('excluded') && m.excluded_expense > 0)}
                    />
                    {on('excluded') && m.excluded_expense > 0 && (
                      <BarPath
                        x={expX}
                        y0={expTop}
                        y1={y(m.expense + m.excluded_expense)}
                        w={barW}
                        className="chart-bar excluded"
                        fill={`url(#${hatchId})`}
                      />
                    )}
                  </>
                )}
                {i % labelEvery === 0 && (
                  <text x={cx} y={HEIGHT - 8} className={`chart-tick ${active ? 'strong' : ''}`} textAnchor="middle">
                    {monthLabel(m.month, locale)}
                  </text>
                )}
              </g>
            )
          })}

          {on('avg') && average > 0 && (
            <g className="chart-avg">
              <line x1={PAD.left} x2={width - PAD.right} y1={y(average)} y2={y(average)} />
              <text x={width - PAD.right} y={y(average) - 4} textAnchor="end">
                {t('reports.avgShort')} {formatCompactYen(average, locale)}
              </text>
            </g>
          )}

          {on('net') && (
            <>
              <polyline className="chart-line" points={months.map((m, i) => `${xCenter(i)},${y(m.net)}`).join(' ')} />
              {months.map((m, i) => (
                <circle key={m.month} cx={xCenter(i)} cy={y(m.net)} r={hover === i ? 5 : 3.5} className="chart-marker" />
              ))}
            </>
          )}

          {hovered && hover !== null && (
            <line x1={xCenter(hover)} x2={xCenter(hover)} y1={PAD.top} y2={HEIGHT - PAD.bottom} className="chart-crosshair" />
          )}

          {/* 最上层透明覆盖：统一处理鼠标与触屏，命中区是整列而不是细细的柱子 */}
          <rect
            x={PAD.left}
            y={PAD.top}
            width={layout.innerW}
            height={innerH}
            fill="transparent"
            style={{ cursor: onPickMonth ? 'pointer' : 'default', touchAction: 'pan-y' }}
            onPointerMove={(e) => setHover(slotFromPointer(e, PAD.left, slot, months.length))}
            onPointerDown={(e) => {
              tap.current = { type: e.pointerType, prev: hover }
              setHover(slotFromPointer(e, PAD.left, slot, months.length))
            }}
            onPointerLeave={(e) => e.pointerType === 'mouse' && setHover(null)}
            onClick={(e) => {
              const i = slotFromPointer(e as unknown as React.PointerEvent<SVGElement>, PAD.left, slot, months.length)
              if (i === null) return
              if (tap.current.type !== 'mouse' && tap.current.prev !== i) return
              onPickMonth?.(months[i].month)
            }}
          />
        </svg>
      )}

      {hovered && hover !== null && (
        <div
          className="chart-tooltip"
          style={{ left: Math.min(Math.max(xCenter(hover), 100), Math.max(width - 100, 100)) }}
        >
          <strong>{monthLabel(hovered.month, locale, true)}</strong>
          <span>
            <i className="swatch income" /> {t('reports.income')}
            <b>{formatJPY(hovered.income, locale)}</b>
          </span>
          <span>
            <i className="swatch expense" /> {t('reports.expense')}
            <b>{formatJPY(hovered.expense, locale)}</b>
          </span>
          {hovered.excluded_expense > 0 && (
            <span>
              <i className="swatch excluded" /> {t('reports.excludedSeries')}
              <b>{formatJPY(hovered.excluded_expense, locale)}</b>
            </span>
          )}
          <span>
            <i className="swatch net" /> {t('reports.net')}
            <b>{formatJPY(hovered.net, locale)}</b>
          </span>
          {average > 0 && hovered.expense > 0 && (
            <em className={hovered.expense > average ? 'bad' : 'good'}>
              {t(hovered.expense > average ? 'reports.aboveAvg' : 'reports.belowAvg', {
                amount: formatJPY(Math.abs(hovered.expense - average), locale),
              })}
            </em>
          )}
          {onPickMonth && hovered.month !== activeMonth && <small>{t('reports.clickToOpen')}</small>}
        </div>
      )}
    </div>
  )
}

function monthLabel(ym: string, locale: string, long = false): string {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 1, 1)
  if (long) return new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short' }).format(d)
  // 一月多带上年份，其他月份只给月，横轴才放得下
  return new Intl.DateTimeFormat(locale, m === 1 ? { year: '2-digit', month: 'short' } : { month: 'short' }).format(d)
}
