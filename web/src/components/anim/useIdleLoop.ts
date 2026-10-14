// Idle loops (a bobbing rabbit, a flickering flame) only run while they can be seen: paused
// when the tab is hidden (document.visibilityState) or the element is offscreen
// (IntersectionObserver). Returns a ref for the element and whether the loop should play.
import { useEffect, useRef, useState } from 'react'

export function useIdleLoop<T extends Element>(enabled = true): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null)
  const [visible, setVisible] = useState(true)
  const [onScreen, setOnScreen] = useState(true)
  useEffect(() => {
    if (!enabled) return
    const vis = () => setVisible(document.visibilityState !== 'hidden')
    vis()
    document.addEventListener('visibilitychange', vis)
    let io: IntersectionObserver | null = null
    const el = ref.current
    if (el && typeof IntersectionObserver !== 'undefined') {
      io = new IntersectionObserver((es) => { for (const e of es) setOnScreen(e.isIntersecting) })
      io.observe(el)
    }
    return () => { document.removeEventListener('visibilitychange', vis); io?.disconnect() }
  }, [enabled])
  return [ref, enabled && visible && onScreen]
}
