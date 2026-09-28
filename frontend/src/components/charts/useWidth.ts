import { useLayoutEffect, useRef, useState } from 'react'

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
