// One-tap actions on the Rabbit home (server: quickactions.py): "How did it feel?", "RSVP",
// "Cheer a friend", "Send to watch". Each is shown only when it applies and completes right
// here (no navigation). At most two at once, so Home stays calm. SharePrompt (the one-time
// "Share my workouts with friends" question) is exported for Home's single next-step slot.
import { useEffect, useState } from 'react'
import { CalendarCheck, Check, PartyPopper, Share2, Smile, Watch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { burst } from '@/components/anim'
import { createCheckin } from '@/lib/checkins'
import { getCommunitySettings, putCommunitySettings, react, rsvpMeetup, type CommunitySettings } from '@/lib/community'
import { fmtDist, fmtDuration } from '@/lib/format'
import { hapticTap } from '@/lib/haptics'
import { syncGarmin } from '@/lib/plan'
import { getQuickActions, type QuickAction } from '@/lib/unread'
import { cn } from '@/lib/utils'

const FACES: [number, string, string][] = [[1, '😣', 'Awful'], [2, '😕', 'Rough'], [3, '😐', 'OK'], [4, '🙂', 'Good'], [5, '😄', 'Great']]

function when(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const today = new Date()
  const tmw = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1)
  const day = d.toDateString() === today.toDateString() ? 'Today'
    : d.toDateString() === tmw.toDateString() ? 'Tomorrow' : d.toLocaleDateString(undefined, { weekday: 'short' })
  return `${day} ${d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`
}

const ICON = { feel: Smile, rsvp: CalendarCheck, cheer: PartyPopper, watch: Watch } as const

/** The action as a title and a quieter second line (the details), so nothing gets cut off. */
function lines(a: QuickAction, imperial: boolean): [string, string | null] {
  switch (a.kind) {
    case 'feel': {
      const bits = [a.km ? fmtDist(a.km, imperial, a.sport) : null, a.minutes ? fmtDuration(a.minutes) : null].filter(Boolean)
      return [`How did your ${a.title.toLowerCase()} feel?`, bits.length ? bits.join(' · ') : null]
    }
    case 'rsvp': return [`Going to ${a.title}?`, when(a.next) || null]
    case 'cheer': return [`Cheer ${a.name}`, `Their ${a.what}`]
    case 'watch': return [`Send ${a.title} to your watch`, null]
  }
}

export function QuickActions({ refreshKey, imperial, skipWatchFor, skipCheer, onToast }: {
  refreshKey?: number; imperial: boolean
  /** "Friends' latest" shows on the home with its own cheers */
  skipCheer?: boolean
  /** today's session already offers "Send to watch" in the Up next card */
  skipWatchFor?: string | null
  onToast: (msg: string) => void
}) {
  const [actions, setActions] = useState<QuickAction[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [feelOpen, setFeelOpen] = useState(false)

  useEffect(() => {
    let live = true
    getQuickActions().then((r) => { if (live) setActions(r.actions) }, () => { if (live) setActions([]) })
    return () => { live = false }
  }, [refreshKey])

  const shown = actions.filter((a) => !(a.kind === 'watch' && skipWatchFor && a.session_id === skipWatchFor)
    && !(a.kind === 'cheer' && skipCheer))

  async function run(a: QuickAction, el: HTMLElement | null, feel?: number) {
    setBusy(a.kind)
    try {
      if (a.kind === 'feel') await createCheckin({ text: '', feel, activity_id: a.activity_id, date: a.date })
      else if (a.kind === 'rsvp') await rsvpMeetup(a.club_id, a.meetup_id, 'going')
      else if (a.kind === 'cheer') await react(a.post_id, 'party')
      else await syncGarmin(7)
      hapticTap()
      if (el && a.kind === 'cheer') burst(el, 'kudos')
      onToast(a.kind === 'feel' ? 'Logged. Thanks!' : a.kind === 'rsvp' ? `You're going to ${a.title}.`
        : a.kind === 'cheer' ? `Cheered ${a.name}.` : 'Sent to your watch.')
      setDone(a.kind)
      setFeelOpen(false)
      window.setTimeout(() => { setActions((xs) => xs.filter((x) => x.kind !== a.kind)); setDone(null) }, 900)
    } catch (e) {
      onToast((e as Error).message || 'That didn\'t work. Try again.')
    } finally {
      setBusy(null)
    }
  }

  const feel = shown.find((a) => a.kind === 'feel')
  if (!shown.length) return null
  return (
    <div data-usage-card="actions" role="group" aria-label="Quick actions"
      className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface) shadow-[var(--shadow-sm)]">
      <ul className="flex flex-col divide-y divide-(--border)">
        {shown.slice(0, 2).map((a) => {
          const Icon = done === a.kind ? Check : ICON[a.kind]
          const active = a.kind === 'feel' && feelOpen
          const [title, sub] = lines(a, imperial)
          return (
            <li key={a.kind}>
              <button type="button" disabled={busy !== null || done === a.kind}
                aria-expanded={a.kind === 'feel' ? feelOpen : undefined}
                className="flex min-h-14 w-full items-center gap-3.5 px-4 py-3 text-left transition-colors active:bg-(--bg-inset) disabled:opacity-60"
                onClick={(e) => a.kind === 'feel' ? setFeelOpen((v) => !v) : void run(a, e.currentTarget)}>
                <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-full',
                  active || done === a.kind ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--accent-subtle) text-(--accent)')}>
                  <Icon className="size-5" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-body font-medium leading-snug text-(--text)">{title}</span>
                  {sub && <span className="mt-0.5 block text-small leading-snug text-(--text-muted)">{sub}</span>}
                </span>
              </button>
              {a.kind === 'feel' && feel && feelOpen && (
                <div role="group" aria-label="How did it feel?" className="flex items-center justify-between gap-1 px-3 pb-3">
                  {FACES.map(([n, face, label]) => (
                    <button key={n} type="button" aria-label={label} disabled={busy !== null}
                      className="flex min-h-14 min-w-11 flex-1 flex-col items-center justify-center rounded-xl text-title-md leading-none active:bg-(--bg-inset) disabled:opacity-50"
                      onClick={() => void run(feel, null, n)}>
                      <span aria-hidden>{face}</span>
                      <span className="mt-1 text-caption text-(--text-muted)">{label}</span>
                    </button>
                  ))}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** The one-time "Share my workouts with friends" card (Home's "next step" slot). Shown once:
 *  being shown turns the default on (server-side), "Keep private" turns it off. Changeable in
 *  Me. `onShown` tells Home whether it's up, so no other prompt stacks under it. */
// Once the question is up it stays up for this visit, even if Home moves it (remounts it) to
// another spot: the server marks it as asked the first time it's shown.
let askedThisVisit = false

export function SharePrompt({ onShown }: { onShown?: (shown: boolean) => void }) {
  const [s, setS] = useState<CommunitySettings | null>(null)
  const [answered, setAnswered] = useState<boolean | null>(null)
  useEffect(() => {
    let live = true
    getCommunitySettings().then((r) => {
      if (!live) return
      setS(r.settings)
      if (r.settings.share_workouts == null && !r.settings.share_prompted) void putCommunitySettings({ share_prompted: true }).catch(() => {})
    }, () => {})
    return () => { live = false }
  }, [])
  const hidden = !s || s.share_workouts != null || (s.share_prompted && answered === null && !askedThisVisit)
  if (!hidden) askedThisVisit = true
  useEffect(() => { onShown?.(!hidden && answered === null) }, [hidden, answered]) // eslint-disable-line react-hooks/exhaustive-deps
  if (hidden) return null
  if (answered !== null) {
    return (
      <p role="status" className="m-0 text-small text-(--text-muted)">
        {answered ? 'Your workouts will show up for friends. Change it anytime in Me.' : 'Kept private. You can turn sharing on in Me.'}
      </p>
    )
  }
  async function choose(v: boolean) {
    setAnswered(v)
    try { await putCommunitySettings({ share_workouts: v }) } catch { setAnswered(null) }
  }
  return (
    <section aria-labelledby="share-prompt-title" className="rounded-xl border border-(--accent)/30 bg-(--bg-surface) p-4 shadow-[var(--shadow-sm)]">
      <h2 id="share-prompt-title" className="m-0 flex items-start gap-2.5 text-body-lg font-semibold leading-snug text-(--text)">
        <Share2 className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden /> Share your workouts with friends?
      </h2>
      <p className="mt-2 text-body leading-snug text-(--text-secondary)">
        Friends who follow you see each new workout: sport, time and distance. Never heart rate, maps or where you trained. It's on unless you say no.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="default" className="min-w-36 flex-1 border-(--accent)/40 font-semibold text-(--accent)" onClick={() => void choose(true)}>Share with friends</Button>
        <Button variant="ghost" className="min-w-36 flex-1" onClick={() => void choose(false)}>Keep private</Button>
      </div>
    </section>
  )
}
