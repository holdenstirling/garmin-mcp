// "Meetups & games near you" in Local: other people's events they made Public (server:
// publicevents.py), in your area, soonest first. Tap "I'm going" to tell the host you'll be there;
// the event's own site opens outside the app. Hidden when there's nothing near you.
import { useEffect, useState } from 'react'
import { Check, ExternalLink, MapPin, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fmtDay } from '@/components/plan/PlanParts'
import { fmtTime } from '@/lib/plancal'
import { listPublicEvents, setPublicGoing, type PublicEvent } from '@/lib/events'
import { SPORT_ICON, isSport } from '@/lib/sports'
import { haptic } from '@/lib/haptics'
import { cn } from '@/lib/utils'

export function PublicEventsNear({ refreshKey }: { refreshKey?: number }) {
  const [rows, setRows] = useState<PublicEvent[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    listPublicEvents().then((r) => { if (live) setRows(r.events) }, () => { if (live) setRows([]) })
    return () => { live = false }
  }, [refreshKey])

  async function toggle(e: PublicEvent) {
    setBusy(e.key); setErr(null)
    try {
      const r = await setPublicGoing(e.key, !e.my_going)
      if (r.my_going) haptic()
      setRows((xs) => xs?.map((x) => x.key === e.key ? { ...x, going: r.going, my_going: r.my_going } : x) ?? xs)
    } catch (x) { setErr((x as Error).message) } finally { setBusy(null) }
  }

  if (!rows || rows.length === 0) return null
  return (
    <section aria-label="Meetups and games near you" className="flex flex-col gap-2">
      <h2 className="px-1 text-caption font-semibold text-(--text-muted)">Meetups &amp; games near you</h2>
      <ul className="flex flex-col gap-2">
        {rows.map((e) => {
          const Icon = isSport(e.activity) ? SPORT_ICON[e.activity] : Users
          const when = [fmtDay(e.next_date, { weekday: 'short', month: 'short', day: 'numeric' }), e.time ? fmtTime(e.time) : ''].filter(Boolean).join(' · ')
          return (
            <li key={e.key} className="flex flex-col gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
              <div className="flex items-start gap-3">
                <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)"><Icon className="size-6" /></span>
                <div className="min-w-0 flex-1">
                  <p className="text-body-lg font-semibold leading-snug text-(--text)">{e.name}</p>
                  <p className="text-meta text-(--text-secondary)">{[e.activity_label, when].filter(Boolean).join(' · ')}</p>
                  {e.repeat_text && <p className="text-meta text-(--text-muted)">{e.repeat_text}</p>}
                  {(e.neighborhood || e.location) && (
                    <p className="mt-0.5 flex items-center gap-1 text-meta text-(--text-muted)"><MapPin className="size-3.5 shrink-0" aria-hidden />{e.neighborhood || e.location}</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <p className="min-w-0 flex-1 truncate text-meta text-(--text-muted)">
                  {e.host}{e.going ? ` · ${e.going} going` : ''}
                </p>
                {e.url && (
                  <a href={e.url} target="_blank" rel="noopener noreferrer" aria-label={`${e.name} website`}
                    className="flex size-11 shrink-0 items-center justify-center rounded-lg border border-(--border) text-(--text-secondary) active:bg-(--bg-inset)">
                    <ExternalLink className="size-5" aria-hidden />
                  </a>
                )}
                <Button variant={e.my_going ? 'default' : 'primary'} className={cn('h-11 shrink-0 gap-1.5 px-4 text-small', e.my_going && 'text-(--accent)')}
                  aria-pressed={e.my_going} loading={busy === e.key} onClick={() => void toggle(e)}>
                  {e.my_going ? <><Check className="size-5" aria-hidden /> Going</> : "I'm going"}
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
      {err && <p className="px-1 text-meta text-(--danger)" role="alert">{err}</p>}
      <p className="px-1 text-caption text-(--text-muted)">Hosting something? Make your event Public and it shows up here for people nearby.</p>
    </section>
  )
}
