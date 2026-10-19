// What ties an event to the rest of Rabbit, on the event's page:
//   * EventPlanCard: how it shows up in the plan (server: events.plan_links) with "See it on
//     your schedule" (lib/plancal openPlanDay) and Build / Update my plan when it isn't in yet;
//   * AddToCalendar: Google Calendar's own add page (repeat included) or an .ics file;
//   * UpcomingDates: a repeating event's next dates, skip one or bring it back;
//   * CalendarSync (Events screen): the private calendar link Google / Apple subscribe to.
import { useEffect, useState } from 'react'
import { CalendarCheck, CalendarDays, CalendarPlus, Check, Copy, Download, ExternalLink, Link2, Ellipsis, RotateCcw, Undo2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/plan/ui'
import { openPlanDay } from '@/lib/plancal'
import {
  editOccurrence, eventIcsUrl, getCalFeed, makeCalFeed, stopCalFeed, type CalFeed, type RaceEvent,
} from '@/lib/events'
import { cn } from '@/lib/utils'

const fmt = (d: string, o: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric' }) =>
  new Date(`${d}T12:00:00`).toLocaleDateString([], o)
const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function EventPlanCard({ event, onBuildPlan, onOpenPlan }: {
  event: RaceEvent; onBuildPlan?: () => void; onOpenPlan?: () => void
}) {
  const link = event.plan
  if (!link) return null
  const on = link.status === 'main' || link.status === 'in_plan'
  const day = link.days.find((d) => d >= todayIso()) ?? link.days[0] ?? (event.next_dates?.[0]) ?? event.date
  return (
    <Card className="flex flex-col gap-2.5 p-4">
      <div className="flex items-start gap-3">
        <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg',
          on ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-inset) text-(--text-muted)')} aria-hidden>
          {on ? <CalendarCheck className="size-4.5" /> : <CalendarDays className="size-4.5" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-body font-semibold text-(--text)">
            {link.status === 'main' ? 'Your plan builds to this' : on ? 'In your plan' : link.status === 'pending' ? 'Not in your plan yet'
              : link.status === 'no_plan' ? 'No plan yet' : link.status === 'past' ? 'Done' : 'On your calendar'}
          </p>
          <p className="text-small leading-snug text-(--text-secondary)">{link.line}</p>
          {on && link.days.length > 1 && (
            <p className="mt-1 text-meta text-(--text-muted)">Plan days: {link.days.slice(0, 4).map((d) => fmt(d)).join(' · ')}{link.days.length > 4 ? ' …' : ''}</p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {link.status !== 'past' && link.status !== 'no_plan' && (
          <Button variant="default" className="h-11 gap-1.5 px-3 text-small" onClick={() => openPlanDay(day)}>
            <CalendarDays className="size-5" aria-hidden /> See it on your schedule
          </Button>
        )}
        {link.action === 'update_plan' && onOpenPlan && (
          <Button variant="primary" className="h-11 gap-1.5 px-3 text-small" onClick={onOpenPlan}>
            <RotateCcw className="size-5" aria-hidden /> Update my plan
          </Button>
        )}
        {link.action === 'build_plan' && onBuildPlan && (
          <Button variant="primary" className="h-11 gap-1.5 px-3 text-small" onClick={onBuildPlan}>
            Build my plan
          </Button>
        )}
      </div>
    </Card>
  )
}

export function AddToCalendar({ event }: { event: RaceEvent }) {
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex min-h-12 w-full items-center gap-2 px-4 text-left text-body font-medium text-(--text) active:bg-(--bg-inset)">
        <CalendarPlus className="size-5 text-(--accent)" aria-hidden />
        <span className="flex-1">Add to calendar{event.recurring ? ' (every date)' : ''}</span>
        <span className="text-meta text-(--text-muted)">{open ? 'Hide' : 'Google, Apple, Outlook'}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-2 border-t border-(--border) p-3">
          {event.google_url && (
            <a href={event.google_url} target="_blank" rel="noopener noreferrer"
              className="flex min-h-11 items-center gap-2 rounded-lg border border-(--border) px-3 text-small font-medium text-(--text) active:bg-(--bg-inset)">
              <ExternalLink className="size-5" aria-hidden /> Google Calendar
              <span className="ml-auto text-small text-(--text-muted)">opens Google’s add page</span>
            </a>
          )}
          <a href={eventIcsUrl(event.id)} download="rabbt-event.ics"
            className="flex min-h-11 items-center gap-2 rounded-lg border border-(--border) px-3 text-small font-medium text-(--text) active:bg-(--bg-inset)">
            <Download className="size-5" aria-hidden /> Apple Calendar or Outlook (.ics)
          </a>
          <p className="text-small leading-snug text-(--text-muted)">
            Changed it later? Add it again and your calendar replaces the old copy. To stay in sync on its own, use “Keep your calendar in sync” on Events.
          </p>
        </div>
      )}
    </Card>
  )
}

/** A repeating event's next dates: skip one (that date only) or bring it back. */
export function UpcomingDates({ event, onSaved }: { event: RaceEvent; onSaved: (list: RaceEvent[]) => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (!event.recurring) return null
  const t = todayIso()
  const skipped = (event.recurring.except ?? []).filter((d) => d >= t)
  const rows = [...(event.next_dates ?? []).map((d) => ({ d, off: false })), ...skipped.map((d) => ({ d, off: true }))]
    .sort((a, b) => a.d.localeCompare(b.d)).slice(0, 8)
  async function run(d: string, skip: boolean) {
    setBusy(d); setError(null)
    try { const r = await editOccurrence(event.id, d, { skip }); onSaved(r.events) }
    catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }
  return (
    <Card>
      <div className="px-4 pt-3">
        <p className="text-body font-semibold text-(--text)">{event.repeat_text ?? 'Repeats'}</p>
        <p className="text-meta text-(--text-muted)">Can’t make one? Skip just that date; the rest stay.</p>
      </div>
      <ul className="mt-1 divide-y divide-(--border)" aria-live="polite">
        {rows.length === 0 && <li className="px-4 py-3 text-small text-(--text-muted)">No dates left.</li>}
        {rows.map(({ d, off }) => (
          <li key={d} className="flex min-h-12 items-center gap-2 px-4">
            <span className={cn('flex-1 text-body', off ? 'text-(--text-muted) line-through' : 'text-(--text)')}>
              {fmt(d, { weekday: 'long', month: 'short', day: 'numeric' })}{event.time ? ` · ${event.time}` : ''}
            </span>
            {off ? (
              <Button variant="ghost" className="h-11 gap-1 px-2 text-meta" loading={busy === d} aria-label={`Bring back ${fmt(d)}`}
                onClick={() => void run(d, false)}><Undo2 className="size-4" aria-hidden /> Bring back</Button>
            ) : (
              <Button variant="ghost" className="h-11 gap-1 px-2 text-meta text-(--text-secondary)" loading={busy === d} aria-label={`Skip ${fmt(d)}`}
                onClick={() => void run(d, true)}><X className="size-4" aria-hidden /> Skip</Button>
            )}
          </li>
        ))}
      </ul>
      {error && <p className="px-4 pb-3 text-meta text-(--danger)" role="alert">{error}</p>}
    </Card>
  )
}

/** The private calendar link: Google / Apple Calendar subscribe once and stay in sync with your
 * events and plan sessions. */
export function CalendarSync() {
  const [feed, setFeed] = useState<CalFeed | null>(null)
  const [busy, setBusy] = useState<'make' | 'stop' | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getCalFeed().then(setFeed, () => setFeed({ on: false })) }, [])
  async function make() {
    setBusy('make'); setError(null)
    try { setFeed(await makeCalFeed()) } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }
  async function stop() {
    setBusy('stop'); setError(null)
    try { setFeed(await stopCalFeed()) } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }
  async function copy(url: string) {
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000) }
    catch { setError('Couldn’t copy. Press and hold the link to copy it.') }
  }
  if (!feed) return null
  // A plain card (not a settings group): no row separators running into the buttons.
  return (
    <section aria-label="Keep your calendar in sync" className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)" aria-hidden><Link2 className="size-4.5" /></span>
        <div className="min-w-0 flex-1">
          <p role="heading" aria-level={3} className="text-body font-semibold text-(--text)">Keep your calendar in sync</p>
          <p className="text-meta leading-snug text-(--text-muted)">
            {feed.on ? 'Your Google or Apple calendar follows your events and workouts on its own.'
              : 'One private link: your events and plan workouts show up in Google or Apple Calendar and stay updated.'}
          </p>
        </div>
        {feed.on && (
          <details className="relative shrink-0">
            <summary aria-label="Calendar link options"
              className="flex size-11 cursor-pointer list-none items-center justify-center rounded-lg text-(--text-muted) active:bg-(--bg-inset) [&::-webkit-details-marker]:hidden">
              <Ellipsis className="size-5" aria-hidden />
            </summary>
            <div className="absolute right-0 top-12 z-20 flex w-52 flex-col overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface) py-1 shadow-lg">
              <button type="button" className="min-h-11 px-3.5 text-left text-small text-(--text) active:bg-(--bg-inset)"
                disabled={busy != null} onClick={() => void make()}>Make a new link</button>
              <button type="button" className="min-h-11 px-3.5 text-left text-small text-(--danger) active:bg-(--bg-inset)"
                disabled={busy != null} onClick={() => void stop()}>Turn off</button>
            </div>
          </details>
        )}
      </div>
      {feed.url ? (
        <>
          <div className="flex items-center gap-2">
            <input readOnly value={feed.url} aria-label="Your private calendar link" onFocus={(e) => e.currentTarget.select()}
              className="h-12 min-w-0 flex-1 rounded-lg border border-(--border) bg-(--bg-inset) px-3 text-body text-(--text-secondary)" />
            <Button variant="default" className="h-12 w-12 shrink-0 p-0" aria-label={copied ? 'Copied' : 'Copy link'} onClick={() => void copy(feed.url!)}>
              {copied ? <Check className="size-5" /> : <Copy className="size-5" />}
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <a href={`https://calendar.google.com/calendar/r?cid=${encodeURIComponent(feed.webcal ?? feed.url)}`} target="_blank" rel="noopener noreferrer"
              className="flex min-h-12 items-center justify-center gap-1.5 rounded-lg border border-(--border) px-2 text-body font-medium text-(--text) active:bg-(--bg-inset)">
              <ExternalLink className="size-5 shrink-0" aria-hidden /> Google
            </a>
            {feed.webcal && (
              <a href={feed.webcal} className="flex min-h-12 items-center justify-center gap-1.5 rounded-lg border border-(--border) px-2 text-body font-medium text-(--text) active:bg-(--bg-inset)">
                <CalendarPlus className="size-5 shrink-0" aria-hidden /> Apple
              </a>
            )}
          </div>
          <p className="text-small leading-snug text-(--text-muted)">
            Anyone with this link can see these dates, so keep it to yourself. Calendars check it every few hours.
          </p>
        </>
      ) : feed.on ? (
        <p className="text-small leading-snug text-(--text-secondary)">Your link is on. rabbt can’t show it again; use ··· to make a new one (the old one stops working).</p>
      ) : (
        <Button variant="default" className="h-12 w-full text-body font-semibold text-(--accent)" loading={busy === 'make'} onClick={() => void make()}>
          Get my calendar link
        </Button>
      )}
      {error && <p className="text-meta text-(--danger)" role="alert">{error}</p>}
    </section>
  )
}
