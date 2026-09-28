/**
 * 金额与日期格式化。
 *
 * 金额一律为整数日元，全链路不出现浮点数。所有格式化都经由此处，
 * 避免各页面各写一套导致「有的地方带￥有的地方不带」。
 */

const jpyFormatters = new Map<string, Intl.NumberFormat>()

function jpyFormatter(locale: string): Intl.NumberFormat {
  let f = jpyFormatters.get(locale)
  if (!f) {
    f = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: 'JPY',
      maximumFractionDigits: 0,
      // 必须显式指定，否则中文/英文环境下 JPY 会被渲染成「JP¥」而非「¥」
      currencyDisplay: 'narrowSymbol',
    })
    jpyFormatters.set(locale, f)
  }
  return f
}

/** 带货币符号：¥1,234 */
export function formatJPY(amount: number, locale = 'zh-CN'): string {
  return jpyFormatter(locale).format(amount)
}

/** 仅千分位，不带符号：1,234 */
export function formatNumber(amount: number, locale = 'zh-CN'): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(amount)
}

/**
 * 图表坐标轴用的短金额：30万 / 300K / ¥0。
 *
 * 中文与日文环境下「万」是自然单位，英文用 K/M；都交给 Intl 的 compact 记法，
 * 不自己拼，否则三种语言要维护三套规则。
 */
export function formatCompactYen(amount: number, locale = 'zh-CN'): string {
  if (amount === 0) return '0'
  return new Intl.NumberFormat(locale, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(amount)
}

/** 百分比：0.1234 → 12.3% */
export function formatPercent(ratio: number, locale = 'zh-CN'): string {
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(ratio)
}

/** 带正负号，用于余额变动等场景：+1,234 / -1,234 */
export function formatSigned(amount: number, locale = 'zh-CN'): string {
  const sign = amount > 0 ? '+' : ''
  return sign + formatJPY(amount, locale)
}

/**
 * 从输入框文本解析出整数日元。
 *
 * 接受全角数字（日文输入法下很容易打出来）、千分位逗号、日元符号。
 * 小数部分直接丢弃——日元没有小数。
 */
export function parseAmount(text: string): number {
  if (!text) return 0
  // 全角数字 → 半角
  const normalized = text.replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
  const digits = normalized.replace(/[^\d]/g, '')
  if (!digits) return 0
  const n = Number.parseInt(digits, 10)
  return Number.isFinite(n) ? n : 0
}

/** 输入过程中的显示值：1234 → 1,234 */
export function formatAmountInput(value: number | ''): string {
  if (value === '' || value === 0) return value === 0 ? '0' : ''
  return new Intl.NumberFormat('en-US').format(value)
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
