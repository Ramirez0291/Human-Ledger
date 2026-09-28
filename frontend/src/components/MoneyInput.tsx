import { useEffect, useState } from 'react'
import { formatAmountInput, parseAmount } from '../lib/format'

interface Props {
  value: number
  onChange: (value: number) => void
  id?: string
  autoFocus?: boolean
  placeholder?: string
}

export function MoneyInput({ value, onChange, id, autoFocus, placeholder }: Props) {
  const [text, setText] = useState(() => (value ? formatAmountInput(value) : ''))

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
