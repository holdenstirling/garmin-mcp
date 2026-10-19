// "Get started" on the Rabbit home for an athlete's first week: six steps that make the app
// worth opening (connect Garmin, a plan, your race, follow 3 friends, join a club, turn on
// notifications), each ticked from what's already true and one tap from where it's done.
// Hides itself once every step is done, after the first week, or on "Hide" (this device).
import { useEffect, useState } from 'react'
import { Bell, CalendarDays, Check, ChevronRight, Flag, MapPin, UserPlus, Watch, X } from 'lucide-react'
import { IconTile } from '@/components/ui/brand'
import { getPeople } from '@/lib/social'
import { getClubs } from '@/lib/community'
import type { Progress } from '@/lib/progress'
import { cn } from '@/lib/utils'

export type StartStep = 'garmin' | 'plan' | 'race' | 'friends' | 'club' | 'notify'
const HIDE = 'rabbit.getstarted.hidden'
const FIRST = 'rabbit.getstarted.first'
const WEEK_MS = 7 * 86_400_000

function firstSeen(): number {
  try {
    const v = Number(window.localStorage.getItem(FIRST))
    if (v > 0) return v
    const now = Date.now(); window.localStorage.setItem(FIRST, String(now)); return now
  } catch { return Date.now() }
}
const hidden = () => { try { return window.localStorage.getItem(HIDE) === '1' } catch { return false } }

export function GetStartedCard({ garmin, hasGoal, progress, onStep }: {
  garmin: boolean; hasGoal: boolean; progress: Progress | null; onStep: (s: StartStep) => void
}) {
  const [gone, setGone] = useState(() => hidden() || Date.now() - firstSeen() > WEEK_MS)
  const [following, setFollowing] = useState<number | null>(null)
  const [clubs, setClubs] = useState<number | null>(null)
  useEffect(() => {
    if (gone) return
    let live = true
    getPeople().then((p) => { if (live) setFollowing(p.following.length + p.pending_out.length) }, () => {})
    getClubs().then((c) => { if (live) setClubs(c.clubs.length) }, () => {})
    return () => { live = false }
  }, [gone])
  if (gone || !progress || following === null || clubs === null) return null

  const q = (id: string) => !!progress.quests.find((x) => x.id === id)?.done
  const notifOn = q('notify') || (typeof Notification !== 'undefined' && Notification.permission === 'granted')
  const steps: { id: StartStep; label: string; sub: string; icon: typeof Watch; done: boolean }[] = [
    { id: 'garmin', label: 'Connect Garmin', sub: 'Your workouts, sleep and recovery', icon: Watch, done: garmin },
    { id: 'plan', label: 'Build or upload a plan', sub: 'rabbt builds one, or bring yours', icon: CalendarDays, done: q('plan') },
    { id: 'race', label: 'Add your race', sub: 'The plan builds toward it', icon: Flag, done: hasGoal || q('goal') },
    { id: 'friends', label: 'Follow 3 friends', sub: following > 0 ? `${Math.min(following, 3)} of 3` : 'See their workouts, cheer them on', icon: UserPlus, done: following >= 3 },
    { id: 'club', label: 'Join a club', sub: 'Group runs and rides near you', icon: MapPin, done: clubs > 0 },
    { id: 'notify', label: 'Turn on notifications', sub: 'Kudos, messages, race reminders', icon: Bell, done: notifOn },
  ]
  const done = steps.filter((s) => s.done).length
  if (done === steps.length) return null
  const hide = () => { try { window.localStorage.setItem(HIDE, '1') } catch { /* storage off */ } setGone(true) }

  return (
    <div className="px-4">
      <section aria-label="Get started" className="mx-auto max-w-2xl rounded-2xl border border-(--border) bg-(--bg-surface) px-3 py-2">
        <div className="flex min-h-9 items-center gap-2">
          <h2 className="font-sans flex-1 text-caption font-semibold text-(--text-muted)">Get started · {done} of {steps.length}</h2>
          <button type="button" onClick={hide} aria-label="Hide Get started" className="hit-44 rounded-full p-1 text-(--text-muted)"><X className="size-5" /></button>
        </div>
        <div className="mb-1 h-1 overflow-hidden rounded-full bg-(--bg-inset)" aria-hidden>
          <div className="h-full rounded-full bg-(--accent) transition-[width]" style={{ width: `${(done / steps.length) * 100}%` }} />
        </div>
        <ul className="flex flex-col">
          {steps.map((s) => (
            <li key={s.id} className="border-t border-(--border) first:border-t-0">
              <button type="button" disabled={s.done} onClick={() => onStep(s.id)}
                className="flex min-h-12 w-full items-center gap-3 py-1.5 text-left disabled:cursor-default">
                <IconTile size={30} tone={s.done ? 'neutral' : undefined}>{s.done ? <Check className="size-5" /> : <s.icon className="size-4" />}</IconTile>
                <span className="min-w-0 flex-1">
                  <span className={cn('block truncate text-small font-medium', s.done ? 'text-(--text-muted) line-through' : 'text-(--text)')}>{s.label}</span>
                  {!s.done && <span className="block truncate text-meta text-(--text-muted)">{s.sub}</span>}
                </span>
                {!s.done && <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />}
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
