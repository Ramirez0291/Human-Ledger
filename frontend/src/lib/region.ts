/**
 * 当前账本的地区包（后端 app/regions）。
 *
 * 一个账本只有一种币种，登录后由 App 按用户设置一次（setLedgerRegion），之后所有金额的
 * 格式化 / 解析都从这里取：API 里的金额是**最小单位的整数**——日元是円，人民币是分。
 * 用模块级状态而不是 Context：格式化函数散落在几十处纯函数与图表里，且整个会话内不会变。
 */

export interface LedgerRegion {
  region: string
  currency: string
  /** 存储的小数位：金额整数 = 显示金额 × 10^minorUnit */
  minorUnit: number
}

let current: LedgerRegion = { region: 'JP', currency: 'JPY', minorUnit: 0 }

export function setLedgerRegion(user: { region?: string; currency?: string; minor_unit?: number } | null) {
  current = {
    region: user?.region ?? 'JP',
    currency: user?.currency ?? 'JPY',
    minorUnit: user?.minor_unit ?? 0,
  }
}

export function ledgerRegion(): LedgerRegion {
  return current
}

/** 10^minorUnit：显示金额 × scale = 存储的整数 */
export function moneyScale(): number {
  return 10 ** current.minorUnit
}

/**
 * 报表「单笔上限」的预设档位（最小单位）。按当地的「一笔大开销」量级给，
 * 而不是按汇率换算：日本 1 万円一档，中国 500 元一档。
 */
export function analysisCaps(): number[] {
  const scale = moneyScale()
  if (current.currency === 'CNY') return [500, 1000, 3000, 5000].map((v) => v * scale)
  return [10_000, 30_000, 50_000, 100_000].map((v) => v * scale)
}

/**
 * 地区专属文案用 i18next 的 context：`t('account.emptyDesc', { context: regionContext() })`
 * 先找 `account.emptyDesc_CN`，没有就退回 `account.emptyDesc`。日本版是基础文案，不加后缀。
 */
export function regionContext(): string | undefined {
  return current.region === 'JP' ? undefined : current.region
}
