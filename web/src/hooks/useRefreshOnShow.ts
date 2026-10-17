// Tabs stay mounted once visited (screens/Chat.tsx), so their data can get old. This re-runs
// `load` quietly (no loader, the current content stays on screen) when a bottom tab is shown
// again and the last load is older than `minAgeMs`.
import { useEffect, useRef } from 'react'
import { TAB_SHOWN_EVENT } from '@/lib/nav'

export function useRefreshOnShow(load: () => unknown, minAgeMs = 60_000) {
  const last = useRef(Date.now())
  const fn = useRef(load)
  fn.current = load
  useEffect(() => {
    const on = () => {
      if (Date.now() - last.current < minAgeMs) return
      last.current = Date.now()
      void fn.current()
    }
    window.addEventListener(TAB_SHOWN_EVENT, on)
    return () => window.removeEventListener(TAB_SHOWN_EVENT, on)
  }, [minAgeMs])
}
