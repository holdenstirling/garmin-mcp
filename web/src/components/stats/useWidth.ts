// The rendered width of an element, so a chart's SVG can use a viewBox of the same width:
// one SVG unit is one CSS pixel and chart labels stay at their real 13px on every phone
// (a fixed viewBox shrinks them to 8-9px on a 320px screen).
import { useLayoutEffect, useRef, useState, type RefObject } from 'react'

export function useWidth<T extends HTMLElement>(fallback: number, min = 240): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null)
  const [w, setW] = useState(fallback)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const read = () => { const x = Math.round(el.getBoundingClientRect().width); if (x > 0) setW(Math.max(min, x)) }
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [min])
  return [ref, w]
}
