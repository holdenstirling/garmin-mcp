// Swipe left/right between the bottom tabs (touch only; the tab bar, keyboard and screen
// readers work exactly as before). The page follows the finger a little and, past a quarter of
// the width or with a quick flick, the next/previous tab takes over.
//
// Only clearly sideways, single-finger swipes count: the move must pass DECIDE_PX with
// |dx| > 1.6 * |dy|, so vertical scrolling and pull-to-refresh are untouched. Ignored when the
// touch starts
//   * within EDGE_PX of the left edge (useEdgeSwipe's "back" lives there),
//   * on a form control, a slider, an editable field, a map or an iframe, or anything marked
//     [data-no-tab-swipe],
//   * inside an element that scrolls sideways (carousels, chip rows, week strips),
//   * while a sheet or overlay page is open (lib/overlays), or text is being selected.
// Reduced motion: no follow, the tab just switches on release.
import { useEffect, useRef } from 'react'
import { overlayOver, prefersReducedMotion } from '@/lib/overlays'

const EDGE_PX = 24
const DECIDE_PX = 12
const RATIO = 1.6
const COMMIT_FRACTION = 0.25
const FLICK_PX_PER_MS = 0.45
const FOLLOW = 0.35

const NO_SWIPE = [
  'input', 'textarea', 'select', '[contenteditable=""]', '[contenteditable="true"]', '[role="slider"]',
  'iframe', 'canvas', '.leaflet-container', '.maplibregl-map', '[data-no-tab-swipe]', '.modal-overlay',
].join(',')

function scrollsSideways(el: Element | null, stop: Element): boolean {
  for (let p = el; p && p !== stop; p = p.parentElement) {
    if (p.scrollWidth > p.clientWidth + 1) {
      const o = getComputedStyle(p).overflowX
      if (o === 'auto' || o === 'scroll') return true
    }
  }
  return false
}

export function swipeTarget<T>(tabs: readonly T[], current: T, dx: number): T | null {
  const i = tabs.indexOf(current)
  if (i < 0) return null
  const j = dx < 0 ? i + 1 : i - 1
  return j >= 0 && j < tabs.length ? tabs[j]! : null
}

export function useTabSwipe<T>(
  ref: React.RefObject<HTMLElement | null>,
  { tabs, current, enabled, onSwipe }: { tabs: readonly T[]; current: T; enabled: boolean; onSwipe: (t: T) => void },
) {
  const cur = useRef(current)
  cur.current = current
  const cb = useRef(onSwipe)
  cb.current = onSwipe

  useEffect(() => {
    const root = ref.current
    if (!root || !enabled) return
    const reduced = prefersReducedMotion()
    let start: { x: number; y: number; t: number } | null = null
    let swiping = false
    let page: HTMLElement | null = null
    let last = { x: 0, t: 0 }
    let v = 0

    const pageOf = (target: Element) => {
      // The visible tab page: the direct child of the root that holds the touch.
      for (let p: Element | null = target; p && p !== root; p = p.parentElement) {
        if (p.parentElement === root) return p as HTMLElement
      }
      return null
    }
    const place = (x: number, transition: string) => {
      if (!page || reduced) return
      page.style.transition = transition
      page.style.transform = x ? `translateX(${x}px)` : ''
      page.style.opacity = x ? String(Math.max(0.6, 1 - Math.abs(x) / (page.offsetWidth || 1))) : ''
    }
    const clear = () => { if (page) { page.style.transition = page.style.transform = page.style.opacity = '' } }

    const onStart = (e: TouchEvent) => {
      start = null
      swiping = false
      const t = e.touches[0]
      const target = e.target instanceof Element ? e.target : null
      if (e.touches.length !== 1 || !t || !target || t.clientX <= EDGE_PX) return
      if (target.closest(NO_SWIPE) || scrollsSideways(target, root) || overlayOver(root)) return
      const sel = window.getSelection?.()
      if (sel && !sel.isCollapsed) return
      start = { x: t.clientX, y: t.clientY, t: e.timeStamp }
      last = { x: t.clientX, t: e.timeStamp }
      v = 0
      page = pageOf(target)
    }
    const onMove = (e: TouchEvent) => {
      const t = e.touches[0]
      if (!start || !t) return
      const dx = t.clientX - start.x, dy = t.clientY - start.y
      if (!swiping) {
        if (Math.hypot(dx, dy) < DECIDE_PX) return
        if (Math.abs(dx) < RATIO * Math.abs(dy) || swipeTarget(tabs, cur.current, dx) === null) { start = null; return }
        swiping = true
      }
      if (e.cancelable) e.preventDefault() // we own this gesture now: no sideways page drift
      const dt = e.timeStamp - last.t
      if (dt > 0) v = (t.clientX - last.x) / dt
      last = { x: t.clientX, t: e.timeStamp }
      place(dx * FOLLOW, 'none')
    }
    const onEnd = () => {
      const s = start, was = swiping
      start = null
      swiping = false
      if (!s || !was) return
      const dx = last.x - s.x
      const width = root.offsetWidth || 1
      const next = swipeTarget(tabs, cur.current, dx)
      const commit = next !== null && (Math.abs(dx) > width * COMMIT_FRACTION || (Math.abs(v) > FLICK_PX_PER_MS && Math.sign(v) === Math.sign(dx)))
      if (!commit || next === null) { place(0, 'transform 180ms ease, opacity 180ms ease'); window.setTimeout(clear, 200); return }
      clear()
      cb.current(next)
      if (!reduced) {
        // The new page slides in from the side it came from.
        requestAnimationFrame(() => {
          const shown = Array.from(root.children).find((c) => c instanceof HTMLElement && c.offsetParent !== null
            && !c.matches('nav, .tab-bar')) as HTMLElement | undefined
          shown?.animate([{ transform: `translateX(${dx < 0 ? 28 : -28}px)`, opacity: 0.6 }, { transform: 'none', opacity: 1 }],
            { duration: 200, easing: 'cubic-bezier(0.2, 0.9, 0.25, 1)' })
        })
      }
    }

    root.addEventListener('touchstart', onStart, { passive: true })
    root.addEventListener('touchmove', onMove, { passive: false })
    root.addEventListener('touchend', onEnd)
    root.addEventListener('touchcancel', onEnd)
    return () => {
      clear()
      root.removeEventListener('touchstart', onStart)
      root.removeEventListener('touchmove', onMove)
      root.removeEventListener('touchend', onEnd)
      root.removeEventListener('touchcancel', onEnd)
    }
  }, [ref, enabled, tabs])
}
