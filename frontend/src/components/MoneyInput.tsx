import { useEffect, useState } from 'react'
import { formatAmountInput, parseAmount } from '../lib/format'

interface Props {
  value: number
  onChange: (value: number) => void
  id?: string
  autoFocus?: boolean
  placeholder?: string
}

/**
 * 日元金额输入。
 *
 * - 只接受整数，输入过程中即显示千分位
 * - 兼容日文输入法下打出的全角数字
 * - inputMode="numeric" 让手机弹出数字键盘（截图记账本就是手机场景）
 */
export function MoneyInput({ value, onChange, id, autoFocus, placeholder }: Props) {
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
        ¥
      </span>
      <input
        id={id}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        autoFocus={autoFocus}
        placeholder={placeholder}
        value={text}
        onChange={(e) => {
          const n = parseAmount(e.target.value)
          setText(e.target.value === '' ? '' : formatAmountInput(n))
          onChange(n)
        }}
      />
    </div>
  )
}
