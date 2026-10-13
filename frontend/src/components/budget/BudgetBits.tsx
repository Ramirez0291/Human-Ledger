import type { TFunction } from 'i18next'
import type { BudgetLine, SpecialBudgetKind } from '../../api/client'
import { formatMoney } from '../../lib/format'
import { ledgerRegion } from '../../lib/region'

export const KIND_ICON: Record<SpecialBudgetKind, string> = {
  holiday: '🎌',
  bonus: '💰',
  treat: '✨',
  other: '📌',
}

/**
 * 预算进度条：实心是已花，淡色段是到月底预计还会花的，细竖线是区间两端，
 * 100% 处是预算线。超出预算的部分画在预算线右侧（条会变红）。
 */
export function BudgetBar({ line, compact = false }: { line: BudgetLine; compact?: boolean }) {
  if (line.budget === null || line.budget <= 0) return null
  // 刻度上限：预算和预测里较大者再留 10%，超出也看得见超了多少
  const scaleMax = Math.max(line.budget, line.high, line.spent) * 1.1
  const pct = (v: number) => `${Math.min(100, (v / scaleMax) * 100)}%`
  const tone =
    line.status === 'over' || line.status === 'will_exceed' || line.status === 'likely_exceed'
      ? 'bad'
      : line.status === 'at_risk'
        ? 'warn'
        : 'ok'
  return (
    <div className={`budget-bar ${tone} ${compact ? 'compact' : ''}`} aria-hidden="true">
      <span className="budget-bar-projected" style={{ width: pct(line.projected) }} />
      <span className="budget-bar-spent" style={{ width: pct(line.spent) }} />
      {line.high > line.low && (
        <span
          className="budget-bar-range"
          style={{
            left: pct(line.low),
            width: `calc(${pct(line.high)} - ${pct(line.low)})`,
          }}
        />
      )}
      <span className="budget-bar-limit" style={{ left: pct(line.budget) }} />
    </div>
  )
}

export function statusTone(status: BudgetLine['status']): 'ok' | 'warn' | 'bad' | 'muted' {
  if (status === 'none') return 'muted'
  if (status === 'on_track') return 'ok'
  if (status === 'at_risk') return 'warn'
  return 'bad'
}

/** 一句话结论：先说结果，再说怎么办 */
export function statusSentence(t: TFunction, line: BudgetLine, locale: string, finished: boolean): string {
  const money = (v: number) => formatMoney(v, locale)
  if (line.budget === null) return t('budget.say.none', { projected: money(line.projected) })
  const left = line.budget - line.spent
  if (finished) {
    return line.spent > line.budget
      ? t('budget.say.pastOver', { spent: money(line.spent), amount: money(-left) })
      : t('budget.say.pastOk', { spent: money(line.spent), amount: money(left) })
  }
  const gap = line.projected - line.budget
  switch (line.status) {
    case 'over':
      return t('budget.say.over', { amount: money(-left) })
    case 'will_exceed':
      return t('budget.say.willExceed', {
        amount: money(gap),
        cut: money(line.cut_per_day ?? 0),
      })
    case 'likely_exceed':
      return t('budget.say.likelyExceed', {
        amount: money(gap),
        cut: money(line.cut_per_day ?? 0),
      })
    case 'at_risk':
      return t('budget.say.atRisk', {
        projected: money(line.projected),
        amount: money(Math.max(0, -gap)),
      })
    default:
      return t('budget.say.onTrack', {
        projected: money(line.projected),
        amount: money(-gap),
      })
  }
}

export function paceText(t: TFunction, ratio: number | null): string | null {
  if (ratio === null) return null
  const diff = Math.round((ratio - 1) * 100)
  if (Math.abs(diff) < 8) return t('budget.paceSame')
  return diff > 0 ? t('budget.paceFaster', { pct: diff }) : t('budget.paceSlower', { pct: -diff })
}

// --------------------------------------------------------------------------
// 特别预算的预设区间（日本的长假与常见由头）
// --------------------------------------------------------------------------

export interface SpecialPreset {
  key: string
  kind: SpecialBudgetKind
  from: string
  to: string
}

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** 下一次（含正在进行的）这个区间：已经过去了就给明年的 */
function upcoming(today: Date, fromMD: [number, number], toMD: [number, number]): [string, string] {
  const y = today.getFullYear()
  for (const year of [y - 1, y, y + 1]) {
    const from = new Date(year, fromMD[0] - 1, fromMD[1])
    const toYear = toMD[0] < fromMD[0] ? year + 1 : year
    const to = new Date(toYear, toMD[0] - 1, toMD[1])
    if (to >= new Date(today.getFullYear(), today.getMonth(), today.getDate())) return [iso(from), iso(to)]
  }
  return [iso(today), iso(today)]
}

// 春节按农历，每年不同：正月初一的公历日期。表外的年份不给春节预设
const LUNAR_NEW_YEAR: Record<number, [number, number]> = {
  2025: [1, 29],
  2026: [2, 17],
  2027: [2, 6],
  2028: [1, 26],
  2029: [2, 13],
  2030: [2, 3],
  2031: [1, 23],
}

/** 下一个（含正在进行的）春节假期：除夕到初六 */
function upcomingSpringFestival(today: Date): [string, string] | null {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  for (const year of [today.getFullYear(), today.getFullYear() + 1]) {
    const md = LUNAR_NEW_YEAR[year]
    if (!md) continue
    const from = new Date(year, md[0] - 1, md[1] - 1)
    const to = new Date(year, md[0] - 1, md[1] + 6)
    if (to >= start) return [iso(from), iso(to)]
  }
  return null
}

/** 节假日预设随账本地区：日本是黄金周 / お盆 / 年末年始，中国是春节 / 五一 / 国庆 / 双十一 */
function holidayPresets(today: Date, region: string): SpecialPreset[] {
  if (region === 'CN') {
    const out: SpecialPreset[] = []
    const sf = upcomingSpringFestival(today)
    if (sf) out.push({ key: 'springFestival', kind: 'holiday', from: sf[0], to: sf[1] })
    const [mayFrom, mayTo] = upcoming(today, [5, 1], [5, 5])
    const [ndFrom, ndTo] = upcoming(today, [10, 1], [10, 7])
    const [d11From, d11To] = upcoming(today, [10, 20], [11, 11])
    out.push(
      { key: 'mayDay', kind: 'holiday', from: mayFrom, to: mayTo },
      { key: 'nationalDay', kind: 'holiday', from: ndFrom, to: ndTo },
      { key: 'double11', kind: 'treat', from: d11From, to: d11To },
    )
    return out
  }
  const [gwFrom, gwTo] = upcoming(today, [4, 29], [5, 5])
  const [obonFrom, obonTo] = upcoming(today, [8, 13], [8, 16])
  const [nyFrom, nyTo] = upcoming(today, [12, 29], [1, 3])
  return [
    { key: 'gw', kind: 'holiday', from: gwFrom, to: gwTo },
    { key: 'obon', kind: 'holiday', from: obonFrom, to: obonTo },
    { key: 'newYear', kind: 'holiday', from: nyFrom, to: nyTo },
  ]
}

export function specialPresets(today = new Date()): SpecialPreset[] {
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1)
  const monthEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0)
  const sat = new Date(today)
  sat.setDate(today.getDate() + ((6 - today.getDay() + 7) % 7))
  const sun = new Date(sat)
  sun.setDate(sat.getDate() + 1)
  return [
    ...holidayPresets(today, ledgerRegion().region),
    { key: 'bonus', kind: 'bonus', from: iso(monthStart), to: iso(monthEnd) },
    { key: 'weekend', kind: 'treat', from: iso(sat), to: iso(sun) },
    { key: 'today', kind: 'treat', from: iso(today), to: iso(today) },
  ]
}
