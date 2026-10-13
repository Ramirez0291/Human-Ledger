/**
 * 金额与日期格式化。
 *
 * 金额一律为**最小货币单位的整数**（日元为円、人民币为分，见 lib/region），全链路不出现浮点数。
 * 所有格式化都经由此处，避免各页面各写一套导致「有的地方带￥有的地方不带」。
 * 只在显示的最后一步除以 10^minorUnit。
 */

import { ledgerRegion, moneyScale } from './region'

const moneyFormatters = new Map<string, Intl.NumberFormat>()

function moneyFormatter(locale: string): Intl.NumberFormat {
  const { currency, minorUnit } = ledgerRegion()
  const key = `${locale}|${currency}|${minorUnit}`
  let f = moneyFormatters.get(key)
  if (!f) {
    f = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      minimumFractionDigits: minorUnit,
      maximumFractionDigits: minorUnit,
      // 必须显式指定，否则中文/英文环境下 JPY 会被渲染成「JP¥」、CNY 成「CN¥」而非「¥」
      currencyDisplay: 'narrowSymbol',
    })
    moneyFormatters.set(key, f)
  }
  return f
}

/** 带货币符号：¥1,234 / ¥23.50 */
export function formatMoney(amount: number, locale = 'zh-CN'): string {
  return moneyFormatter(locale).format(amount / moneyScale())
}

/** 账本币种的符号：输入框前缀用 */
export function moneySymbol(locale = 'zh-CN'): string {
  return moneyFormatter(locale).formatToParts(0).find((p) => p.type === 'currency')?.value ?? '¥'
}

/** 仅千分位，不带符号：1,234 / 23.50 */
export function formatNumber(amount: number, locale = 'zh-CN'): string {
  const { minorUnit } = ledgerRegion()
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: minorUnit,
    maximumFractionDigits: minorUnit,
  }).format(amount / moneyScale())
}

/**
 * 图表坐标轴用的短金额：30万 / 300K / ¥0。
 *
 * 中文与日文环境下「万」是自然单位，英文用 K/M；都交给 Intl 的 compact 记法，
 * 不自己拼，否则三种语言要维护三套规则。
 */
export function formatCompactMoney(amount: number, locale = 'zh-CN'): string {
  if (amount === 0) return '0'
  return new Intl.NumberFormat(locale, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(amount / moneyScale())
}

/** 百分比：0.1234 → 12.3% */
export function formatPercent(ratio: number, locale = 'zh-CN'): string {
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(ratio)
}

/** 带正负号，用于余额变动等场景：+1,234 / -1,234 */
export function formatSigned(amount: number, locale = 'zh-CN'): string {
  const sign = amount > 0 ? '+' : ''
  return sign + formatMoney(amount, locale)
}

/** 全角数字 / 全角句点 → 半角（日文、中文输入法下很容易打出来） */
function toHalfWidth(text: string): string {
  return text
    .replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/[．。]/g, '.')
}

/**
 * 从输入框文本解析出最小单位的整数。
 *
 * 接受全角数字、千分位逗号、货币符号。小数部分按账本的小数位截取：
 * 人民币「23.5」→ 2350；日元没有小数，「1234.5」→ 1234。
 */
export function parseAmount(text: string): number {
  if (!text) return 0
  const { minorUnit } = ledgerRegion()
  const [intPart, fracPart = ''] = toHalfWidth(text).split('.', 2)
  const whole = intPart.replace(/[^\d]/g, '')
  const frac = fracPart.replace(/[^\d]/g, '').slice(0, minorUnit).padEnd(minorUnit, '0')
  if (!whole && !/[1-9]/.test(frac)) return 0
  const n = Number.parseInt(whole || '0', 10) * 10 ** minorUnit + (minorUnit ? Number.parseInt(frac, 10) : 0)
  return Number.isFinite(n) ? n : 0
}

/** 从数值得到输入框的显示值：1234 → 1,234；人民币 2350 → 23.50、20000 → 200 */
export function formatAmountInput(value: number | ''): string {
  if (value === '') return ''
  const { minorUnit } = ledgerRegion()
  const scale = moneyScale()
  const whole = value % scale === 0
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: whole ? 0 : minorUnit,
    maximumFractionDigits: minorUnit,
  }).format(value / scale)
}

/**
 * 输入过程中的显示值：保留用户正在打的小数点与小数位，只给整数部分加千分位。
 * 「23.」不能被立刻改写成「23」，否则永远打不出小数。
 */
export function formatAmountTyping(text: string): string {
  const { minorUnit } = ledgerRegion()
  const half = toHalfWidth(text)
  const dot = minorUnit > 0 ? half.indexOf('.') : -1
  const intDigits = (dot >= 0 ? half.slice(0, dot) : half).replace(/[^\d]/g, '').replace(/^0+(?=\d)/, '')
  const grouped = intDigits ? new Intl.NumberFormat('en-US').format(Number(intDigits)) : dot >= 0 ? '0' : ''
  if (dot < 0) return grouped
  return `${grouped}.${half.slice(dot + 1).replace(/[^\d]/g, '').slice(0, minorUnit)}`
}

// ---- 日期 ----

export function todayISO(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function currentYearMonth(): string {
  return todayISO().slice(0, 7)
}

/** 相对当前月份偏移，用于月份切换：'2026-09' + (-1) → '2026-08' */
export function shiftYearMonth(ym: string, delta: number): string {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export function monthRange(ym: string): { from: string; to: string } {
  const [y, m] = ym.split('-').map(Number)
  const last = new Date(y, m, 0).getDate()
  return { from: `${ym}-01`, to: `${ym}-${String(last).padStart(2, '0')}` }
}

/** 列表里的短日期：9月7日 / Sep 7 / 9月7日 */
export function formatDateShort(iso: string, locale = 'zh-CN'): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(
    new Date(y, m - 1, d),
  )
}

export function formatYearMonth(ym: string, locale = 'zh-CN'): string {
  const [y, m] = ym.split('-').map(Number)
  return new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'long' }).format(
    new Date(y, m - 1, 1),
  )
}

/** 列表分组用的星期几标签 */
export function formatWeekday(iso: string, locale = 'zh-CN'): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(y, m - 1, d))
}
