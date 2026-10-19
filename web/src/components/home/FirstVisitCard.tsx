// First visit without Garmin (server: /app/api/firstvisit): invited friends arrive with no
// watch connected. A short "What you can do now" card on Rabbit home with four things that
// work right away and "Connect Garmin" as the one primary action. Hidden once Garmin is
// connected; "Not now" hides it on this device.
import { useEffect, useState } from 'react'
import { CalendarDays, MapPin, Newspaper, UserPlus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getFirstVisit, type FirstVisit, type FirstVisitItem } from '@/lib/upnext'

const HIDE = 'rabbit.firstvisit.hidden'
const ICON: Record<FirstVisitItem['id'], typeof MapPin> = { clubs: MapPin, events: CalendarDays, feed: Newspaper, friends: UserPlus }

/** "Not now" was tapped on this device (the home status banner then offers Connect Garmin). */
export function firstVisitHidden(): boolean {
  try { return window.localStorage.getItem(HIDE) === '1' } catch { return false }
}

export function FirstVisitCard({ connected, onConnect, onOpen }: {
  connected: boolean
  onConnect: () => void
  onOpen: (id: FirstVisitItem['id']) => void
}) {
  const [fv, setFv] = useState<FirstVisit | null>(null)
  const [gone, setGone] = useState(firstVisitHidden)
  useEffect(() => {
    if (connected || gone) return
    let live = true
    getFirstVisit().then((r) => { if (live) setFv(r) }, () => {})
    return () => { live = false }
  }, [connected, gone])
  if (connected || gone || !fv?.show) return null
  const dismiss = () => {
    try { window.localStorage.setItem(HIDE, '1') } catch { /* this session only */ }
    setGone(true)
  }
  return (
    <section aria-labelledby="fv-title" className="relative shrink-0 rounded-xl border border-(--border) bg-(--bg-surface) p-4 shadow-[var(--shadow-sm)]">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="m-0 text-meta font-medium text-(--text-muted)">What you can do now</p>
          <h2 id="fv-title" className="m-0 mt-0.5 text-lead font-semibold leading-snug text-(--text)">{fv.title}</h2>
        </div>
        <button type="button" onClick={dismiss} aria-label="Not now"
          className="-mr-2 -mt-2 flex size-11 shrink-0 items-center justify-center rounded-full text-(--text-muted) hover:bg-(--bg-inset)">
          <X className="size-5" aria-hidden />
        </button>
      </div>
      <ul className="mt-3 grid grid-cols-1 gap-2 min-[400px]:grid-cols-2">
        {fv.items.map((it) => {
          const Icon = ICON[it.id]
          return (
            <li key={it.id}>
              <button type="button" onClick={() => onOpen(it.id)}
                className="flex min-h-14 w-full items-center gap-3 rounded-lg border border-(--border) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
                <Icon className="size-5 shrink-0 text-(--accent)" aria-hidden />
                <span className="min-w-0">
                  <span className="block text-body font-medium leading-snug text-(--text)">{it.title}</span>
                  <span className="block text-small leading-snug text-(--text-muted)">{it.detail}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      <Button variant="default" className="mt-4 w-full border-(--accent)/40 font-semibold text-(--accent)" onClick={onConnect}>{fv.primary.label}</Button>
      <p className="mt-2 text-center text-small text-(--text-muted)">{fv.primary.detail}</p>
    </section>
  )
}
