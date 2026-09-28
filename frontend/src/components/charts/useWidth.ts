import { useLayoutEffect, useRef, useState } from 'react'

/**
 * 量出容器宽度，让 SVG 按真实像素布局。
 *
 * 不用 viewBox 缩放：那样文字会随容器一起被拉伸，手机上刻度字会糊成一团。
 */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(el.clientWidth)
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setWidth(Math.floor(e.contentRect.width))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return [ref, width]
}
