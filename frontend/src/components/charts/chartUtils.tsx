
export function niceStep(raw: number): number {
  if (raw <= 0) return 1
  const mag = 10 ** Math.floor(Math.log10(raw))
  const n = raw / mag
  const f = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10
  return f * mag
}

export function niceScale(maxValue: number, minValue = 0, ticks = 4) {
  const hi = Math.max(1, maxValue)
  const lo = Math.min(0, minValue)
  const step = niceStep((hi - lo) / ticks)
  const top = Math.ceil(hi / step) * step
  const bottom = Math.floor(lo / step) * step
  const values: number[] = []
  for (let v = bottom; v <= top + step / 2; v += step) values.push(v)
  return { top, bottom, step, values }
}

export function BarPath({
  x,
  y0,
  y1,
  w,
  className,
  fill,
  roundTop = true,
}: {
  x: number
  y0: number
  y1: number
  w: number
  className?: string
  fill?: string
  roundTop?: boolean
}) {
  const h = Math.max(0, y0 - y1)
  if (h < 0.5 || w <= 0) return null
  const r = roundTop ? Math.min(4, w / 2, h) : 0
  const d =
    r > 0
      ? `M${x},${y0} v${-(h - r)} a${r},${r} 0 0 1 ${r},${-r} h${w - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} z`
      : `M${x},${y0} v${-h} h${w} v${h} z`
  return <path d={d} className={className} fill={fill} />
}

export function HatchPattern({ id, className }: { id: string; className: string }) {
  return (
    <pattern id={id} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="6" height="6" className={`${className} hatch-bg`} />
      <line x1="0" y1="0" x2="0" y2="6" className={`${className} hatch-line`} />
    </pattern>
  )
}

export function slotFromPointer(
  e: React.PointerEvent<SVGElement>,
  left: number,
  slot: number,
  count: number,
): number | null {
  const rect = (e.currentTarget.ownerSVGElement ?? (e.currentTarget as SVGSVGElement)).getBoundingClientRect()
  const x = e.clientX - rect.left - left
  if (slot <= 0) return null
  const i = Math.floor(x / slot)
  return i >= 0 && i < count ? i : null
}
