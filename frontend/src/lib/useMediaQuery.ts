import { useEffect, useState } from 'react'

/** 订阅一条媒体查询。用于「宽屏左栏常驻记账表单、窄屏用弹窗」这类需要换组件的场合——纯样式差异用 CSS 即可 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' && 'matchMedia' in window ? window.matchMedia(query).matches : false,
  )
  useEffect(() => {
    if (!('matchMedia' in window)) return
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])
  return matches
}

/** 与 styles.css 里 .workspace 的断点保持一致 */
export const WIDE_QUERY = '(min-width: 1100px)'
