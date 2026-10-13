import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatAmountInput, formatAmountTyping, moneySymbol, parseAmount } from '../lib/format'
import { ledgerRegion } from '../lib/region'

interface Props {
  value: number
  onChange: (value: number) => void
  id?: string
  autoFocus?: boolean
  placeholder?: string
}

/**
 * 金额输入（账本币种）。值为最小单位的整数（日元为円、人民币为分）。
 *
 * - 输入过程中即显示千分位；有小数位的币种保留正在打的小数点
 * - 兼容日文 / 中文输入法下打出的全角数字与句点
 * - 手机弹出数字键盘（截图记账本就是手机场景）；有小数位时用带小数点的键盘
 */
export function MoneyInput({ value, onChange, id, autoFocus, placeholder }: Props) {
  const { i18n } = useTranslation()
  const [text, setText] = useState(() => (value ? formatAmountInput(value) : ''))

  // 外部改值（如编辑已有交易）时同步显示
  useEffect(() => {
    const parsed = parseAmount(text)
    if (parsed !== value) setText(value ? formatAmountInput(value) : '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return (
    <div className="money-input">
      <span className="money-symbol" aria-hidden="true">
        {moneySymbol(i18n.resolvedLanguage ?? 'zh-CN')}
      </span>
      <input
        id={id}
        type="text"
        inputMode={ledgerRegion().minorUnit ? 'decimal' : 'numeric'}
        autoComplete="off"
        autoFocus={autoFocus}
        placeholder={placeholder}
        value={text}
        onChange={(e) => {
          setText(formatAmountTyping(e.target.value))
          onChange(parseAmount(e.target.value))
        }}
      />
    </div>
  )
}
