// Events: races, group activities, trips, challenges and life events on your calendar. Add,
// edit, look up, delete, and pick the main one (the race or challenge your plan builds
// toward). Other races become B/C race days in the plan; group activities become sessions,
// trips lighten those days and life events get rest days.
import { useRefreshOnShow } from '@/hooks/useRefreshOnShow'
import { EmptyState } from '@/components/ui/EmptyState'
import { useCallback, useEffect, useState } from 'react'
import { Activity, Backpack, Bike, ChevronDown, ChevronRight, Compass, Footprints, Gauge, Globe, Layers, Mountain, Repeat, Search, Star, Trash2, Volleyball, Waves, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { shareToFriends } from '@/lib/dm'
import { ShareButton } from '@/components/ui/ShareSheet'
import { HopIn, PullToRefresh } from '@/components/anim'
import { celebrate } from '@/components/fx/motion'
import { Card, Field, Screen, areaCls, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { ChecklistButton, ChecklistRow } from './ChecklistLink'
import {
  DISTANCE_LABEL, KIND_LABEL, MAIN_KINDS, OPEN_EVENT_EVENT, TYPE_LABEL, countdown, deleteEvent, daysUntil, isRace, isUpcoming, kindOf,
  listEvents, makeMainEvent, nextDate, takeOpenEvent, writeDebrief,
  type Debrief, type EventFields, type EventKind, type EventType, type RaceEvent,
} from '@/lib/events'
import { EventBasics, EventGoal, EventKindFields, EventVisibility, InfoBlock, KIND_ICON, KindPicker, kindDefaults } from './EventForm'
import { RacePackScreen, packTitle } from './RacePackScreen'
import { AddToCalendar, CalendarSync, EventPlanCard, UpcomingDates } from './EventLinks'
import { RaceFitScreen } from './RaceFitScreen'
import { ReadinessRow } from './Readiness'
import { FinishChip } from './FinishEstimate'
import { listReadiness, type RaceGrade } from '@/lib/readiness'
import { getPeopleSummary, type PeopleSummary } from '@/lib/racepeople'
import { FollowingRaces, PeopleRow, PeopleSheet, RaceInvitesInbox } from './RacePeople'
import { EventsSkeleton } from '@/components/ui/Skeleton'
import { useDraft } from '@/lib/drafts'
import { saveDurably } from '@/lib/outbox'
import { SaveStatus } from '@/components/ui/SaveStatus'
import { DraftRestored, useUnsavedGuard } from '@/components/ui/UnsavedGuard'
import { ACTIVITY_LABEL, classifyActivity, type ActivityId } from '@/lib/activity'
import { ACTIVITY_ICON } from '@/components/local/ActivityIcon'
import { SPORT_ACTIVITY, SPORT_ICON, isSport, sportLabel } from '@/lib/sports'
import { AreaBar } from '@/components/local/AreaBar'
import { Related } from '@/components/nav/Related'
import { WhoElse } from '@/components/people/WhoElse'
import { openChecklist } from '@/lib/racechecklist'
import { CalendarDays, ListChecks } from 'lucide-react'
import { Section } from '@/components/ui/section'

/** What an event is for (lib/activity): its words first ("Baker volleyball"), then its type. */
function eventActivity(e: RaceEvent): ActivityId {
  if (isSport(e.activity) && e.activity !== 'other') return SPORT_ACTIVITY[e.activity]  // the sport picked in the form
  return classifyActivity([e.name, e.neighborhood, e.location, e.activity_other], e.type)
}

const TYPE_ICON: Record<EventType, typeof Bike> = {
  triathlon: Layers, duathlon: Layers, running: Footprints, trail: Mountain, cycling: Bike,
  swimming: Waves, mountaineering: Mountain, team_sport: Volleyball, other: Activity,
}

export function EventsScreen({ hasBuiltPlan, onClose, onChanged, onOpenPlan, onBuildPlan, imperial = true, request, onRequestHandled, onDiscover }: {
  hasBuiltPlan: boolean
  /** Schedule > Discover: races and meetups near my area */
  onDiscover?: () => void
  /** none when it is the Events tab page (no X) */
  onClose?: () => void
  onChanged: () => void
  onOpenPlan: () => void
  onBuildPlan: () => void
  imperial?: boolean
  /** Schedule "+ Add" -> An event (add) or an event tapped on the plan calendar (open), once per n */
  request?: { add?: boolean; open?: string; n: number } | null
  onRequestHandled?: () => void
}) {
  const [events, setEvents] = useState<RaceEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [editing, setEditing] = useState<RaceEvent | 'new' | null>(null)
  const [showPast, setShowPast] = useState(false)
  const [changed, setChanged] = useState(false)
  const [fit, setFit] = useState<RaceEvent | null>(null)
  const [pack, setPack] = useState<RaceEvent | null>(null)
  const [grades, setGrades] = useState<Record<string, RaceGrade>>({})
  const [people, setPeople] = useState<Record<string, PeopleSummary>>({})
  const [peopleFor, setPeopleFor] = useState<RaceEvent | null>(null)
  const [followKey, setFollowKey] = useState(0)

  const load = useCallback(() => {
    setError(null)
    // Grades are a bonus on the cards: a failure just leaves the plain "Readiness" row.
    listReadiness().then((r) => setGrades(Object.fromEntries(r.races.map((g) => [g.event_id, g]))), () => {})
    getPeopleSummary().then((r) => setPeople(r.events), () => {}) // People rows: a bonus too
    return listEvents().then((r) => setEvents(r.events), (e) => setError((e as Error).message))
  }, [])
  useEffect(() => { void load() }, [load])
  useRefreshOnShow(() => load())
  useEffect(() => {
    if (!request || events === null) return
    const hit = request.open ? events.find((e) => e.id === request.open) : undefined
    if (request.add) setEditing('new')
    else if (hit) setEditing(hit)
    onRequestHandled?.()
  }, [request?.n, events === null]) // eslint-disable-line react-hooks/exhaustive-deps
  // An event opened from elsewhere (a plan day's "From: …", search): lib/events openEvent.
  const [want, setWant] = useState<string | null>(() => takeOpenEvent())
  useEffect(() => {
    const on = (e: Event) => { takeOpenEvent(); setWant((e as CustomEvent<string>).detail || null) }
    window.addEventListener(OPEN_EVENT_EVENT, on)
    return () => window.removeEventListener(OPEN_EVENT_EVENT, on)
  }, [])
  useEffect(() => {
    if (!want || !events) return
    const hit = events.find((e) => e.id === want)
    if (hit) setEditing(hit)
    setWant(null)
  }, [want, events])

  const close = onClose && (() => { setClosing(true); setTimeout(onClose, 200) })
  // Search my events: name, place, neighborhood or activity ("volleyball", "Baker").
  const [q, setQ] = useState('')
  const match = (e: RaceEvent) => {
    const t = q.trim().toLowerCase()
    if (t.length < 2) return true
    return [e.name, e.location, e.neighborhood, TYPE_LABEL[e.type], ACTIVITY_LABEL[eventActivity(e)]]
      .some((x) => typeof x === 'string' && x.toLowerCase().includes(t))
  }
  const upcoming = (events ?? []).filter(isUpcoming).filter(match).sort((a, b) => nextDate(a).localeCompare(nextDate(b)))
  const past = (events ?? []).filter((e) => !isUpcoming(e)).filter(match).reverse()
  const searching = q.trim().length >= 2
  const saved = (list: RaceEvent[]) => { setEvents(list); setChanged(true); onChanged() }

  // "Add" waits for the list: whether a new event becomes the main one depends on it.
  return (
    <>
      {/* Adding lives in Schedule's "+ Add" (and the empty state), not a second button here. */}
      <Screen title="Events" subtitle="Races, group runs and trips" closing={closing} onClose={close}>
        <PullToRefresh onRefresh={load} disabled={events === null && !error} />
        {events === null && !error ? (
          <EventsSkeleton />
        ) : error ? (
          <p className="px-1 text-body text-(--danger)">
            {error} <button type="button" className="hit-44 underline" onClick={() => void load()}>Retry</button>
          </p>
        ) : (
          <>
            <AreaBar imperial={imperial} what="races, group runs and meetups" />
            {onDiscover && (
              <button type="button" onClick={onDiscover}
                className="flex min-h-11 items-center gap-2 rounded-xl border border-dashed border-(--border-strong) px-3.5 text-left text-small font-medium text-(--accent) active:bg-(--bg-inset)">
                <Compass className="size-5 shrink-0" aria-hidden />
                <span className="flex-1">Find races and meetups in your area</span>
                <ChevronRight className="size-5 shrink-0" aria-hidden />
              </button>
            )}
            {(events?.length ?? 0) > 3 && (
              <label className="flex h-11 items-center gap-2 rounded-full border border-(--border) bg-(--bg-surface) px-3.5 focus-within:ring-1 focus-within:ring-(--accent)">
                <Search className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
                <input type="text" inputMode="search" enterKeyHint="search" value={q} maxLength={60} onChange={(e) => setQ(e.target.value)}
                  placeholder="Search my events" aria-label="Search my events by name, place or activity"
                  className="min-w-0 flex-1 bg-transparent text-body text-(--text) outline-none placeholder:text-(--text-muted)" />
                {q && <button type="button" aria-label="Clear search" onClick={() => setQ('')}
                  className="-mr-2 flex size-11 items-center justify-center text-(--text-muted)"><X className="size-5" aria-hidden /></button>}
              </label>
            )}
            {searching && upcoming.length === 0 && past.length === 0 && (
              <p className="px-1 text-small text-(--text-muted)">None of your events match “{q.trim()}”.</p>
            )}
            <RaceInvitesInbox onChanged={() => { void load(); setFollowKey((k) => k + 1) }} />
            {changed && (
              <div className="flex flex-wrap items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-4 py-3.5">
                <p className="min-w-[12rem] flex-1 text-body leading-snug text-(--accent)">
                  {hasBuiltPlan ? 'Rebuild your plan to fit these changes in.' : 'Get a plan built around your main event.'}
                </p>
                <Button variant="default" className="h-11 px-4 text-body font-semibold text-(--accent)" onClick={hasBuiltPlan ? onOpenPlan : onBuildPlan}>
                  {hasBuiltPlan ? 'Open plan' : 'Build plan'}
                </Button>
              </div>
            )}
            {upcoming.length === 0 && !searching && (
              <EmptyState title="Nothing on the calendar yet"
                body="Add races, group rides, trips and big days. rabbt plans around all of them."
                action="Add an event" onAction={() => setEditing('new')} />
            )}
            {upcoming.length > 0 && (
              <Section title="Coming up" description="Tap an event to see it in full or change it.">
                {upcoming.map((e, i) => (
                  <HopIn key={e.id} index={i}>
                    <EventCard e={e} grade={grades[e.id]} people={people[e.id]} onPeople={() => setPeopleFor(e)} onClick={() => setEditing(e)}
                      onFit={kindOf(e) === 'milestone' ? undefined : () => setFit(e)}
                      onPack={daysUntil(e.date) <= 21 && kindOf(e) !== 'milestone' ? () => setPack(e) : undefined} />
                  </HopIn>
                ))}
              </Section>
            )}
            <FollowingRaces refreshKey={followKey} />
            {past.length > 0 && (
              <section className="flex flex-col gap-3">
                <button type="button" onClick={() => setShowPast((v) => !v)}
                  className="flex min-h-11 items-center gap-1.5 px-1 text-body font-semibold text-(--text-secondary)">
                  Past events ({past.length}) <ChevronRight className={cn('size-5 transition-transform', showPast && 'rotate-90')} />
                </button>
                {(showPast || searching) && past.map((e, i) => <HopIn key={e.id} index={i}><EventCard e={e} onClick={() => setEditing(e)} /></HopIn>)}
              </section>
            )}
            <CalendarSync />
            <details className="px-1 text-meta leading-snug text-(--text-muted)">
              <summary className="hit-44 inline-flex min-h-11 cursor-pointer list-none items-center gap-1 font-medium text-(--accent) [&::-webkit-details-marker]:hidden">How events shape your plan <ChevronDown className="size-4" aria-hidden /></summary>
              <p>
                Your <Star className="inline size-3.5 -translate-y-px fill-current" /> main event is what your plan builds toward.
                Other races go into the plan as race days: B races get a short taper, training races are raced as hard workouts.
                Group activities count as sessions, trips keep those days light and life events get rest days.
              </p>
            </details>
          </>
        )}
      </Screen>
      {editing && (
        <EventEditor key={editing === 'new' ? 'new' : editing.id} event={editing === 'new' ? null : editing}
          isFirst={events !== null && events.length === 0} imperial={imperial}
          onClose={() => setEditing(null)} onSaved={(list) => { saved(list) }}
          onUpdated={(list) => { saved(list); setEditing((cur) => cur && cur !== 'new' ? list.find((x) => x.id === cur.id) ?? cur : cur) }}
          onOpenEvent={(id) => { const hit = events?.find((x) => x.id === id); if (hit) setEditing(hit) }}
          onOpenPlan={onOpenPlan} onBuildPlan={onBuildPlan} />
      )}
      {fit && <RaceFitScreen eventId={fit.id} race={isRace(fit)} onClose={() => setFit(null)} />}
      {pack && <RacePackScreen eventId={pack.id} kind={kindOf(pack)} imperial={imperial} onClose={() => setPack(null)} />}
      {peopleFor && <PeopleSheet eventId={peopleFor.id} eventName={peopleFor.name} onClose={() => setPeopleFor(null)}
        onChanged={() => { getPeopleSummary().then((r) => setPeople(r.events), () => {}) }} />}
    </>
  )
}

function EventCard({ e, grade, people, onPeople, onClick, onFit, onPack }: {
  e: RaceEvent; grade?: RaceGrade; people?: PeopleSummary; onPeople?: () => void; onClick: () => void; onFit?: () => void; onPack?: () => void
}) {
  const n = daysUntil(nextDate(e))
  const race = isRace(e)
  if (!onFit && !onPeople) return <EventCardButton e={e} onClick={onClick} />
  return (
    <div className={cn('overflow-hidden rounded-xl border bg-(--bg-surface)', e.main ? 'border-(--accent)' : 'border-(--border)', !isUpcoming(e) && 'opacity-70')}>
      <EventCardButton e={e} onClick={onClick} bare />
      {!onFit ? null : !race ? (
        <button type="button" onClick={onFit}
          className="flex min-h-12 w-full items-center gap-2.5 border-t border-(--border) px-4 py-2.5 text-left text-body font-medium text-(--accent) active:bg-(--bg-inset)">
          <Gauge className="size-5" /> Event prep <ChevronRight className="ml-auto size-5 text-(--text-muted)" />
        </button>
      ) : grade ? <ReadinessRow g={grade} onClick={onFit} extra={n >= 0 ? <FinishChip eventId={e.id} /> : undefined} /> : (
        <button type="button" onClick={onFit}
          className="flex min-h-12 w-full flex-wrap items-center gap-2.5 border-t border-(--border) px-4 py-2.5 text-left text-body font-medium text-(--accent) active:bg-(--bg-inset)">
          <Gauge className="size-5" /> Readiness and race fit
          <span className="ml-auto flex items-center gap-1.5">
            {n >= 0 && <FinishChip eventId={e.id} />}<ChevronRight className="size-5 text-(--text-muted)" />
          </span>
        </button>
      )}
      {onPack && (
        <button type="button" onClick={onPack}
          className="flex min-h-12 w-full items-center gap-2.5 border-t border-(--border) px-4 py-2.5 text-left text-body font-medium text-(--accent) active:bg-(--bg-inset)">
          <Backpack className="size-5" /> {packTitle(kindOf(e))} <ChevronRight className="ml-auto size-5 text-(--text-muted)" />
        </button>
      )}
      {(kindOf(e) === 'race' || kindOf(e) === 'challenge' || kindOf(e) === 'trip') && n >= -7 && <ChecklistRow eventId={e.id} />}
      {onPeople && <PeopleRow s={people} onOpen={onPeople} />}
    </div>
  )
}

function EventCardButton({ e, onClick, bare }: { e: RaceEvent; onClick: () => void; bare?: boolean }) {
  const kind = kindOf(e)
  // The activity's icon (a volleyball night is a volleyball, a group ride a bike), same as Local.
  const act = eventActivity(e)
  const Icon = isSport(e.activity) && e.activity !== 'other' ? SPORT_ICON[e.activity]
    : act !== 'other' ? ACTIVITY_ICON[act] : kind === 'race' ? TYPE_ICON[e.type] ?? Activity : KIND_ICON[kind]
  const when = nextDate(e)
  const n = daysUntil(when)
  const dateLine = (e.recurring && e.repeat_text ? `${e.repeat_text}${e.time ? `, ${e.time}` : ''}`
    : new Date(`${e.date}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }))
    + (e.end_date && e.end_date !== e.date ? ` – ${new Date(`${e.end_date}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}` : '')
  const what = [kind === 'milestone' ? '' : sportLabel(e) ?? TYPE_LABEL[e.type],
    kind !== 'race' || !e.distance || e.distance === 'other' ? '' : DISTANCE_LABEL[e.distance] ?? e.distance].filter(Boolean).join(', ')
  const where = [e.location || e.at || '', e.neighborhood ?? ''].filter(Boolean).join(', ')
  return (
    <button type="button" onClick={onClick}
      className={cn('flex w-full items-start gap-3.5 bg-(--bg-surface) px-4 py-4 text-left active:bg-(--bg-inset)',
        !bare && 'rounded-xl border', !bare && (e.main ? 'border-(--accent)' : 'border-(--border)'), !bare && !isUpcoming(e) && 'opacity-70')}>
      <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-xl',
        e.main ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--accent-subtle) text-(--accent)')}>
        <Icon className="size-6" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-lead font-semibold leading-snug text-(--text)">
          {e.main && <Star className="mr-1.5 inline size-5 -translate-y-px fill-(--accent) align-middle text-(--accent)" aria-label="Main event" />}
          {e.name}
          {e.visibility === 'public' && <Globe className="ml-1.5 inline size-4 align-middle text-(--text-muted)" aria-label="Public" />}
        </span>
        <span className="mt-0.5 block text-small text-(--text-secondary)">{dateLine}</span>
        {(what || where) && <span className="block text-small text-(--text-muted)">{[what, where].filter(Boolean).join(' · ')}</span>}
        <span className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="rounded-full bg-(--bg-inset) px-2.5 py-0.5 text-caption font-semibold text-(--text-secondary)">
            {e.main ? 'Main event' : kind !== 'race' ? KIND_LABEL[kind] : e.priority === 'C' ? 'Training race' : `${e.priority} race`}
          </span>
          <span className="rounded-full bg-(--bg-inset) px-2.5 py-0.5 text-caption font-semibold text-(--text-secondary)">
            {e.result && n < 0 ? e.result : e.recurring && isUpcoming(e) ? `Next: ${countdown(when)}` : countdown(when)}
          </span>
          {e.plan && (e.plan.status === 'in_plan' || e.plan.status === 'pending') && (
            <span className={cn('flex items-center gap-1 rounded-full px-2.5 py-0.5 text-caption font-semibold',
              e.plan.status === 'in_plan' ? 'bg-(--accent-subtle) text-(--accent)' : 'bg-(--warning-subtle) text-(--warning-text)')}>
              {e.recurring && <Repeat className="size-3.5" aria-hidden />}{e.plan.status === 'in_plan' ? 'In your plan' : 'Not in your plan yet'}
            </span>
          )}
        </span>
      </span>
      <ChevronRight className="mt-3 size-5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}

function EventEditor({ event, isFirst, onClose, onSaved, onUpdated, onOpenEvent, onOpenPlan, onBuildPlan, imperial, only, newTitle }: {
  event: RaceEvent | null; isFirst: boolean; imperial: boolean
  /** a new event offers only these kinds, with this title (see NewEventSheet) */
  only?: EventKind[]; newTitle?: string
  onClose: () => void; onSaved: (list: RaceEvent[]) => void
  /** a change made on the page (skip a date) that keeps it open */
  onUpdated: (list: RaceEvent[]) => void
  onOpenEvent: (id: string) => void
  onOpenPlan: () => void; onBuildPlan: () => void
}) {
  const [closing, setClosing] = useState(false)
  // A new event starts with the kind picker; the rest of the form follows the kind.
  // Draft per event (or the new one): kept on this device until it's saved or discarded.
  const [v, setV, draft] = useDraft<EventFields>(`event.${event?.id ?? 'new'}`,
    () => event ? { ...event, kind: kindOf(event) } : {}, { label: event ? `changes to ${event.name}` : 'new event' })
  const guard = useUnsavedGuard(draft.dirty, draft.discard)
  const [queued, setQueued] = useState(false)
  const kind: EventKind | null = event ? kindOf(event) : (v.kind ?? null)
  const canBeMain = kind != null && MAIN_KINDS.includes(kind)
  const race = kind === 'race'
  const [mainPick, setMain] = useState(isFirst)
  const main = mainPick && canBeMain
  const [busy, setBusy] = useState<'save' | 'delete' | 'main' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [pack, setPack] = useState(false)
  const [fitOpen, setFitOpen] = useState(false)
  const set = (p: EventFields) => setV((x) => ({ ...x, ...p }))
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const past = !!event && !isUpcoming(event)

  async function run(kind: 'save' | 'delete' | 'main', fn: () => Promise<{ events: RaceEvent[] }>) {
    setBusy(kind); setError(null); setQueued(false)
    try { const r = await fn(); draft.clear(); onSaved(r.events); close() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }

  function payload(): EventFields {
    const f: EventFields = {}
    for (const k of ['name', 'kind', 'type', 'distance', 'date', 'location', 'url', 'priority', 'goal_type', 'target_time', 'course', 'notes', 'result', 'info', 'elevation_m', 'course_profile',
      'end_date', 'time', 'recurring', 'with', 'at', 'duration_min', 'intensity', 'neighborhood', 'in_plan',
      'activity', 'activity_other', 'visibility'] as const) {
      if (v[k] !== undefined && (!event || JSON.stringify(v[k]) !== JSON.stringify(event[k]))) (f as Record<string, unknown>)[k] = v[k]
    }
    // Skipped dates are saved as you tap them (UpcomingDates): send the latest ones, never the
    // copy the form opened with.
    if (f.recurring && event?.recurring) f.recurring = { ...f.recurring, except: event.recurring.except ?? [] }
    if (f.recurring && !event) f.recurring = { ...f.recurring, except: [] }
    if (f.goal_type !== undefined && f.goal_type !== 'time' && !event?.target_time) delete f.target_time
    if (v.goal_type !== 'time' && event?.target_time) f.target_time = null
    return f
  }

  return (
    <Screen title={event ? event.name : newTitle ?? 'Add an event'} subtitle={event?.main ? 'Your main event' : undefined}
      closing={closing} onClose={guard.wrap(close)} onBack={guard.wrap(close)}
      footer={<>
        <Button variant="primary" className="h-11 flex-1 text-body" loading={busy === 'save'}
          disabled={!kind || !(v.name ?? '').trim() || !v.date || (!!event && !draft.dirty)}
          onClick={(e) => {
            const btn = e.currentTarget
            void run('save', async () => {
              // Durable: offline / 5xx -> "Not saved yet — we'll retry" (lib/outbox, idempotent).
              if (event) return saveDurably<{ events: RaceEvent[] }>({ method: 'PATCH', path: `/api/events/${event.id}`,
                body: payload(), label: 'event', coalesce: `event.${event.id}` }, () => setQueued(true))
              const r = await saveDurably<{ events: RaceEvent[] }>({ method: 'POST', path: '/api/events',
                body: { ...payload(), main }, label: 'event' }, () => setQueued(true))
              celebrate(btn, 'race') // a new event on the calendar
              return r
            })
          }}>
          {!kind ? 'Pick what it is' : !(v.name ?? '').trim() ? 'Give it a name' : !v.date ? 'Pick a date' : event ? (draft.dirty ? 'Save changes' : 'No changes yet') : 'Add event'}
        </Button>
      </>}>
      {draft.restored && <DraftRestored onDiscard={draft.discard} />}
      {guard.dialog}
      {event?.series_id && (
        <button type="button" onClick={() => onOpenEvent(event.series_id!)}
          className="flex min-h-11 items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 text-left text-small text-(--text-secondary) active:bg-(--bg-inset)">
          <Repeat className="size-5 text-(--accent)" aria-hidden /> <span className="flex-1">One date of a repeating event</span>
          <span className="font-medium text-(--accent)">See the series</span>
        </button>
      )}
      {event && <EventPlanCard event={event} onOpenPlan={() => { onOpenPlan(); close() }} onBuildPlan={() => { onBuildPlan(); close() }} />}
      {event && !past && <UpcomingDates event={event} onSaved={onUpdated} />}
      {event && !past && <ChecklistButton eventId={event.id} onBefore={close} />}
      {event && !past && <AddToCalendar event={event} />}
      {event && !past && (
        <ShareButton label="Share or text this event" target={{ kind: 'event', ref: event.id, label: event.name }}
          onSendInRabbit={() => shareToFriends({ type: 'event', ref: { id: event.id }, label: event.name })} />
      )}
      {!event && <KindPicker only={only} value={kind} onChange={(k) => setV((x) => ({ ...kindDefaults(k, isFirst), name: x.name, date: x.date, location: x.location }))} />}
      {kind && (<>
      <EventBasics value={v} onChange={set} eventId={event?.id} allowPast={past} />
      <EventKindFields value={v} onChange={set} />
      {kind !== 'milestone' && <EventVisibility value={v} onChange={set} />}
      {v.info && <Card className="p-4"><InfoBlock info={v.info} /></Card>}
      {(race || kind === 'challenge') && (
        <EventGoal value={v} onChange={set} hidePriority={event?.main || !race} imperial={imperial} raceOnly={race} />
      )}
      <Card>
        <Field label="Notes" hint="Logistics, travel, who's coming, gear to sort.">
          <textarea className={areaCls} value={v.notes ?? ''} maxLength={1000} onChange={(e) => set({ notes: e.target.value })} />
        </Field>
        {past && (
          <Field label="Result" className="border-t border-(--border)" hint="Finish time, place, how it went.">
            <input className={inputCls} value={v.result ?? ''} maxLength={120} placeholder="e.g. 5:41:12, 23rd AG"
              onChange={(e) => set({ result: e.target.value })} />
          </Field>
        )}
      </Card>
      {event && past && race && <DebriefCard event={event} result={v.result ?? ''} notes={v.notes ?? ''} onSaved={(list) => onSaved(list)} />}
      </>)}
      {!event && !isFirst && canBeMain && (
        <label className="flex items-center gap-3 px-1 text-body text-(--text)">
          <input type="checkbox" className="size-4 accent-(--accent)" checked={main} onChange={(e) => setMain(e.target.checked)} />
          Make this my main event (the plan builds toward it)
        </label>
      )}
      {event && !past && kind !== 'milestone' && (
        <div className="flex gap-2">
          <Button variant="default" className="h-11 flex-1 gap-1.5 text-body" onClick={() => setPack(true)}>
            <Backpack className="size-5" /> {packTitle(kind)}
          </Button>
          <Button variant="default" className="h-11 flex-1 gap-1.5 text-body" onClick={() => setFitOpen(true)}>
            <Gauge className="size-5" /> {race ? 'Readiness' : 'Event prep'}
          </Button>
        </div>
      )}
      {fitOpen && event && <RaceFitScreen eventId={event.id} race={race} onClose={() => setFitOpen(false)} />}
      {pack && event && <RacePackScreen eventId={event.id} kind={kind} imperial={imperial} onClose={() => setPack(false)} />}
      {event && !event.main && !past && canBeMain && (
        <Button variant="default" className="h-11 gap-1.5 text-body" loading={busy === 'main'}
          onClick={() => void run('main', () => makeMainEvent(event.id))}>
          <Star className="size-5" /> Make this my main event
        </Button>
      )}
      {event && kind !== 'milestone' && (
        <WhoElse eventName={event.name} eventDate={event.date} invite={!past}
          share={{ type: 'event', ref: { id: event.id }, label: event.name }} />
      )}
      {event && (
        <Related items={[
          { key: 'checklist', icon: <ListChecks className="size-5" />, label: 'Race checklist', sub: 'What to do before the day',
            onClick: !past && kind !== 'milestone' ? () => { close(); window.setTimeout(() => openChecklist(event.id), 220) } : null },
          { key: 'plan', icon: <CalendarDays className="size-5" />, label: 'Your plan', sub: event.main ? 'Built toward this' : 'Your training around it',
            onClick: () => { onOpenPlan(); close() } },
          { key: 'series', icon: <Repeat className="size-5" />, label: 'The whole series', onClick: event.series_id ? () => onOpenEvent(event.series_id!) : null },
        ]} link={{ kind: 'event', id: event.id }} />
      )}
      {event && !event.main && (confirmDelete ? (
        <div className="flex items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3">
          <span className="min-w-0 flex-1 text-body">Delete {event.name}?</span>
          <Button variant="default" className="h-11 px-4 text-body" onClick={() => setConfirmDelete(false)}>Keep</Button>
          <Button variant="destructive" className="h-11 px-4 text-body" loading={busy === 'delete'}
            onClick={() => void run('delete', () => deleteEvent(event.id))}>Delete</Button>
        </div>
      ) : (
        <Button variant="ghost" className="h-10 gap-1.5 text-small text-(--danger)" onClick={() => setConfirmDelete(true)}>
          <Trash2 className="size-5" /> Delete event
        </Button>
      ))}
      {queued && busy === 'save' && <SaveStatus state="queued" className="px-1" />}
      {error && <p className="px-1 text-small text-(--danger)" role="alert">{error}</p>}
    </Screen>
  )
}

function DebriefCard({ event, result, notes, onSaved }: {
  event: RaceEvent; result: string; notes: string; onSaved: (list: RaceEvent[]) => void
}) {
  const [feel, setFeel] = useState<number | null>(event.debrief?.feel ?? null)
  const [d, setD] = useState<Debrief | null>(event.debrief ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function write() {
    setBusy(true); setError(null)
    try {
      const r = await writeDebrief(event.id, { result, notes, ...(feel ? { feel } : {}) })
      setD(r.debrief); onSaved(r.events)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return (
    <Card>
      <Field label="Race debrief" hint="rabbt reads your race from Garmin plus your notes, then saves learnings it carries into your next plan.">
        <div className="flex flex-wrap gap-2">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" onClick={() => setFeel(n)} aria-pressed={feel === n}
              className={cn('plan-chip', feel === n && 'plan-chip--on')}>{['Rough', 'Hard', 'OK', 'Good', 'Great'][n - 1]}</button>
          ))}
        </div>
        <Button variant="primary" className="h-10 text-small" loading={busy} onClick={() => void write()}>
          {d ? 'Rewrite my debrief' : 'Write my debrief'}
        </Button>
        {error && <p className="text-meta text-(--danger)">{error}</p>}
        {d && (
          <div className="flex flex-col gap-2 rounded-lg bg-(--bg-inset) p-3 text-small leading-snug">
            <p className="text-(--text)">{d.summary}</p>
            {d.went_well.length > 0 && <p><b className="text-(--accent)">Went well:</b> <span className="text-(--text-secondary)">{d.went_well.join('; ')}</span></p>}
            {d.work_on.length > 0 && <p><b className="text-(--warning-text)">Work on:</b> <span className="text-(--text-secondary)">{d.work_on.join('; ')}</span></p>}
            {d.learnings.length > 0 && <p><b className="text-(--text)">For your next plan:</b> <span className="text-(--text-secondary)">{d.learnings.join('; ')}</span></p>}
          </div>
        )}
      </Field>
    </Card>
  )
}

/** A new event right where you are (no jump to another tab): Near me's "Post a meetup"
 * offers meetup kinds; Plan's "Add to my calendar" offers race, trip and life days. */
export function NewEventSheet({ only, title, imperial = true, onClose, onSaved, onOpenPlan, onBuildPlan }: {
  only: EventKind[]; title: string; imperial?: boolean
  onClose: () => void; onSaved?: () => void; onOpenPlan: () => void; onBuildPlan: () => void
}) {
  return (
    <EventEditor event={null} isFirst={false} imperial={imperial} only={only} newTitle={title}
      onClose={onClose} onSaved={() => onSaved?.()} onUpdated={() => {}} onOpenEvent={() => {}}
      onOpenPlan={onOpenPlan} onBuildPlan={onBuildPlan} />
  )
}
