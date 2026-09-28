
const jpyFormatters = new Map<string, Intl.NumberFormat>()

function jpyFormatter(locale: string): Intl.NumberFormat {
  let f = jpyFormatters.get(locale)
  if (!f) {
    f = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: 'JPY',
      maximumFractionDigits: 0,
      // Otherwise JPY renders as "JP¥"
      currencyDisplay: 'narrowSymbol',
    })
    jpyFormatters.set(locale, f)
  }
  return f
}

export function formatJPY(amount: number, locale = 'zh-CN'): string {
  return jpyFormatter(locale).format(amount)
}

export function formatNumber(amount: number, locale = 'zh-CN'): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(amount)
}

export function formatCompactYen(amount: number, locale = 'zh-CN'): string {
  if (amount === 0) return '0'
  return new Intl.NumberFormat(locale, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(amount)
}

export function formatPercent(ratio: number, locale = 'zh-CN'): string {
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(ratio)
}

export function formatSigned(amount: number, locale = 'zh-CN'): string {
  const sign = amount > 0 ? '+' : ''
  return sign + formatJPY(amount, locale)
}

export function parseAmount(text: string): number {
  if (!text) return 0
  const normalized = text.replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
  const digits = normalized.replace(/[^\d]/g, '')
  if (!digits) return 0
  const n = Number.parseInt(digits, 10)
  return Number.isFinite(n) ? n : 0
}

export function formatAmountInput(value: number | ''): string {
  if (value === '' || value === 0) return value === 0 ? '0' : ''
  return new Intl.NumberFormat('en-US').format(value)
}

export function todayISO(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function currentYearMonth(): string {
  return todayISO().slice(0, 7)
}

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

export function formatWeekday(iso: string, locale = 'zh-CN'): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(y, m - 1, d))
}
