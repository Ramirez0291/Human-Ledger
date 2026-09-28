import { useEffect, useRef, useState } from 'react'

export interface LazyOption {
  value: number | string
  label: string
}

interface Props {
  value: number | string | ''
  options: LazyOption[]
  onChange: (value: string) => void
  disabled?: boolean
  placeholder: string
  className?: string
  title?: string
}

// Renders a button until clicked, then a native <select>.
// Keeps large staging tables from creating tens of thousands of DOM nodes.
export function LazySelect({ value, options, onChange, disabled, placeholder, className, title }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSelectElement>(null)

  useEffect(() => {
    if (!open) return
    const el = ref.current
    if (!el) return
    el.focus()
    try {
      el.showPicker?.()
    } catch {
    }
  }, [open])

  if (open) {
    return (
      <select
        ref={ref}
        className={className}
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(false)
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false)
        }}
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    )
  }

  const current = options.find((o) => String(o.value) === String(value))
  return (
    <button
      type="button"
      className={`lazy-select ${className ?? ''} ${current ? '' : 'empty'}`}
      disabled={disabled}
      title={title}
      onClick={() => setOpen(true)}
    >
      <span className="lazy-select-label">{current ? current.label : placeholder}</span>
      <span className="lazy-select-caret" aria-hidden="true">
        ▾
      </span>
    </button>
  )
}
