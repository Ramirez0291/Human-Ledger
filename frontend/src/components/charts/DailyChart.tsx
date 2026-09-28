import { useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { DailyReport } from '../../api/client'
import { formatCompactYen, formatJPY } from '../../lib/format'
import { BarPath, HatchPattern, niceScale, slotFromPointer } from './chartUtils'
import { useWidth } from './useWidth'

interface Props {
  data: DailyReport
  locale: string
  today: number | null
  selectedDay: number | null
  onPickDay: (day: number | null) => void
}

const HEIGHT = 220
const PAD = { top: 14, right: 8, bottom: 24, left: 48 }

export function DailyChart({ data, locale, today, selectedDay, onPickDay }: Props) {
  const { t } = useTranslation()
  const [ref, width] = useWidth<HTMLDivElement>()
  const [mode, setMode] = useState<'daily' | 'cumulative'>('daily')
  const [hover, setHover] = useState<number | null>(null)
  const hatchId = `dhatch-${useId().replace(/:/g, '')}`
  const tap = useRef<{ type: string; prev: number | null }>({ type: 'mouse', prev: null })

  const n = data.days.length
  const cum = useMemo(() => {
    let a = 0
    let b = 0
    return data.days.map((d, i) => {
      a += d.expense
      b += data.previous[i]?.expense ?? 0
      return { day: d.day, current: a, previous: b }
    })
  }, [data])

  const lastDay = today ?? n
  const paceDay = Math.min(lastDay, n)
  const pace = cum[paceDay - 1]

  const layout = useMemo(() => {
    const innerW = Math.max(0, width - PAD.left - PAD.right)
    const innerH = HEIGHT - PAD.top - PAD.bottom
    const max =
      mode === 'daily'
        ? Math.max(0, ...data.days.map((d) => d.expense + d.excluded))
        : Math.max(0, ...cum.map((c) => Math.max(c.current, c.previous)))
    const scale = niceScale(max)
    const y = (v: number) => PAD.top + ((scale.top - v) / (scale.top - scale.bottom)) * innerH
    const slot = n ? innerW / n : 0
    return { innerW, innerH, y, slot, ticks: scale.values }
  }, [width, mode, data, cum, n])

  const { y, slot, innerH, innerW, ticks } = layout
  const x = (i: number) => PAD.left + slot * i + slot / 2
  const zero = y(0)
  const barW = Math.max(2, Math.min(16, slot - 3))
  const focus = hover ?? (selectedDay ? selectedDay - 1 : null)
  const focused = focus !== null ? data.days[focus] : null

  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const cur = focus ?? paceDay - 1
      setHover(Math.min(n - 1, Math.max(0, cur + (e.key === 'ArrowRight' ? 1 : -1))))
    } else if (e.key === 'Enter' && hover !== null) {
      onPickDay(hover + 1)
    } else if (e.key === 'Escape') {
      setHover(null)
      onPickDay(null)
    }
  }

  const pathOf = (vals: number[]) => vals.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join(' ')

  return (
    <div className="chart" ref={ref}>
      <div className="chart-toolbar">
        <div className="segmented source-toggle" role="group">
          <button type="button" aria-pressed={mode === 'daily'} onClick={() => setMode('daily')}>
            {t('reports.dailyMode')}
          </button>
          <button type="button" aria-pressed={mode === 'cumulative'} onClick={() => setMode('cumulative')}>
            {t('reports.cumulativeMode')}
          </button>
        </div>
        {pace && pace.previous > 0 && (
          <span className={`pace ${pace.current > pace.previous ? 'bad' : 'good'}`}>
            {t(pace.current > pace.previous ? 'reports.paceFaster' : 'reports.paceSlower', {
              day: paceDay,
              amount: formatJPY(Math.abs(pace.current - pace.previous), locale),
            })}
          </span>
        )}
      </div>

      {width > 0 && (
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={t('reports.dailyTitle')}
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

          {focus !== null && (
            <rect x={PAD.left + slot * focus} y={PAD.top} width={slot} height={innerH} className="chart-focus-col" />
          )}

          {mode === 'daily' &&
            data.days.map((d, i) => {
              const cx = x(i) - barW / 2
              const top = y(d.expense)
              const future = today !== null && d.day > today
              return (
                <g key={d.day} className={future ? 'future' : ''}>
                  <BarPath
                    x={cx}
                    y0={zero}
                    y1={top}
                    w={barW}
                    className={`chart-bar expense ${selectedDay === d.day ? 'selected' : ''}`}
                    roundTop={d.excluded === 0}
                  />
                  {d.excluded > 0 && (
                    <BarPath x={cx} y0={top} y1={y(d.expense + d.excluded)} w={barW} className="chart-bar excluded" fill={`url(#${hatchId})`} />
                  )}
                </g>
              )
            })}

          {mode === 'cumulative' && (
            <>
              <path className="chart-line prev" d={pathOf(cum.map((c) => c.previous))} />
              <path className="chart-line current" d={pathOf(cum.slice(0, lastDay).map((c) => c.current))} />
              {pace && <circle cx={x(paceDay - 1)} cy={y(pace.current)} r={4} className="chart-marker current" />}
            </>
          )}

          {today !== null && today <= n && (
            <line x1={x(today - 1)} x2={x(today - 1)} y1={PAD.top} y2={HEIGHT - PAD.bottom} className="chart-today" />
          )}

          {data.days.map((d, i) =>
            d.day === 1 || d.day % 5 === 0 ? (
              <text key={d.day} x={x(i)} y={HEIGHT - 6} textAnchor="middle" className={`chart-tick ${selectedDay === d.day ? 'strong' : ''}`}>
                {d.day}
              </text>
            ) : null,
          )}

          <rect
            x={PAD.left}
            y={PAD.top}
            width={innerW}
            height={innerH}
            fill="transparent"
            style={{ cursor: 'pointer', touchAction: 'pan-y' }}
            onPointerMove={(e) => setHover(slotFromPointer(e, PAD.left, slot, n))}
            onPointerDown={(e) => {
              tap.current = { type: e.pointerType, prev: hover }
              setHover(slotFromPointer(e, PAD.left, slot, n))
            }}
            onPointerLeave={(e) => e.pointerType === 'mouse' && setHover(null)}
            onClick={(e) => {
              const i = slotFromPointer(e as unknown as React.PointerEvent<SVGElement>, PAD.left, slot, n)
              if (i === null) return
              if (tap.current.type !== 'mouse' && tap.current.prev !== i) return
              onPickDay(selectedDay === i + 1 ? null : i + 1)
            }}
          />
        </svg>
      )}

      {focused && focus !== null && (
        <div className="chart-tooltip" style={{ left: Math.min(Math.max(x(focus), 100), Math.max(width - 100, 100)) }}>
          <strong>{dayLabel(data.year_month, focused.day, locale)}</strong>
          <span>
            <i className="swatch expense" /> {t('reports.expense')}
            <b>{formatJPY(focused.expense, locale)}</b>
          </span>
          {focused.excluded > 0 && (
            <span>
              <i className="swatch excluded" /> {t('reports.excludedSeries')}
              <b>{formatJPY(focused.excluded, locale)}</b>
            </span>
          )}
          <span>
            <i className="swatch expense-soft" /> {t('reports.cumulative')}
            <b>{formatJPY(cum[focus].current, locale)}</b>
          </span>
          <span>
            <i className="swatch prev" /> {t('reports.prevSameDay')}
            <b>{formatJPY(cum[focus].previous, locale)}</b>
          </span>
          {hover !== null && <small>{t('reports.clickForDay')}</small>}
        </div>
      )}

      {mode === 'cumulative' && (
        <div className="chart-legend">
          <span>
            <i className="swatch expense" /> {t('reports.thisMonth')}
          </span>
          <span>
            <i className="swatch prev" /> {t('reports.lastMonth')}
          </span>
        </div>
      )}
    </div>
  )
}

function dayLabel(ym: string, day: number, locale: string): string {
  const [y, m] = ym.split('-').map(Number)
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', weekday: 'short' }).format(
    new Date(y, m - 1, day),
  )
}
