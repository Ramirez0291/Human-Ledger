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
  /** 没有选中值时显示的文字 */
  placeholder: string
  className?: string
  title?: string
}

/**
 * 点了才变成 <select> 的下拉框。
 *
 * 待确认区一个批次几百行、每行三个下拉框，每个又带几十个 <option>——
 * 全部真实渲染会有两三万个 DOM 节点，勾一个复选框都卡。
 * 平时只渲染一个按钮显示当前值，点击时才换成原生 select 并自动展开；
 * 选完或失焦立刻换回按钮。
 */
export function LazySelect({ value, options, onChange, disabled, placeholder, className, title }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSelectElement>(null)

  useEffect(() => {
    if (!open) return
    const el = ref.current
    if (!el) return
    el.focus()
    // 尽量直接弹出选项列表；不支持 showPicker 的浏览器需要用户再点一下
    try {
      el.showPicker?.()
    } catch {
      /* 非用户手势触发时会抛，忽略 */
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
