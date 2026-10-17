// Sick mode from anywhere: lib/sick openSick() opens the sheet over whatever is on screen
// (Add sheet, Schedule tools, Home, Rabbit's check-in). SickBanner is the quiet line on Home and
// Schedule while sick mode or the easy return is on.
import { useEffect, useState } from 'react'
import { RabbitNap } from '@/components/anim'
import { OPEN_SICK_EVENT, SICK_CHANGED_EVENT, getSick, openSick, type SickView } from '@/lib/sick'
import { SickSheet } from './SickSheet'

export function SickHost({ today, onToast }: { today?: string; onToast?: (msg: string) => void }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const on = () => setOpen(true)
    window.addEventListener(OPEN_SICK_EVENT, on)
    return () => window.removeEventListener(OPEN_SICK_EVENT, on)
  }, [])
  return open ? <SickSheet today={today} onClose={() => setOpen(false)} onDone={onToast} /> : null
}

export function useSick(): SickView | null {
  const [v, setV] = useState<SickView | null>(null)
  useEffect(() => {
    let live = true
    const load = () => { getSick().then((x) => { if (live) setV(x) }, () => {}) }
    load()
    window.addEventListener(SICK_CHANGED_EVENT, load)
    return () => { live = false; window.removeEventListener(SICK_CHANGED_EVENT, load) }
  }, [])
  return v
}

/** "Sick mode · day 2 · Rest up" (tap: manage) or "Easing back · day 1 of 4" with when the plan resumes (not tappable). Nothing otherwise. */
export function SickBanner({ className }: { className?: string }) {
  const v = useSick()
  if (!v || (!v.active && !v.returning)) return null
  const head = v.active ? `Sick mode · day ${v.day}` : `Easing back · day ${v.returning!.day} of ${v.returning!.days}`
  const until = v.returning ? new Date(`${v.returning.until}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) : ''
  const sub = v.active ? 'Rest up. Tap when you feel better.' : `Easy, shorter days through ${until}. Then your plan picks up as written, no catching up.`
  const body = (
    <>
      <RabbitNap size={30} mode={v.active ? 'sleep' : 'run'} className="shrink-0" />
      <span className="min-w-0 flex-1">
        <span className="block text-[0.8235rem] font-semibold text-(--text)">{head}</span>
        <span className="block text-[0.7059rem] leading-snug text-(--text-muted)">{sub}</span>
      </span>
    </>
  )
  const cls = 'rb-hop-in flex w-full items-center gap-3 rounded-2xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left'
  return (
    <div className={className}>
      {v.active ? (
        <button type="button" onClick={openSick} aria-label={`${head}. ${sub}`} className={`${cls} active:bg-(--bg-inset)`}>
          {body}
          <span className="shrink-0 rounded-full bg-(--accent-subtle) px-2.5 py-1 text-[0.7059rem] font-semibold text-(--accent)">I feel better</span>
        </button>
      ) : <div role="status" className={cls}>{body}</div>}
    </div>
  )
}
