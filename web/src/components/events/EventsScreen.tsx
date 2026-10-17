// Events: races, group activities, trips, challenges and life events on your calendar. Add,
// edit, look up, delete, and pick the main one (the race or challenge your plan builds
// toward). Other races become B/C race days in the plan; group activities become sessions,
// trips lighten those days and life events get rest days.
import { EmptyState } from '@/components/ui/EmptyState'
import { useCallback, useEffect, useState } from 'react'
import { Activity, Backpack, Bike, CalendarPlus, ChevronRight, Footprints, Gauge, Layers, Mountain, Repeat, Star, Trash2, Volleyball, Waves } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { HopIn, PullToRefresh } from '@/components/anim'
import { celebrate } from '@/components/fx/motion'
import { Card, Field, Screen, areaCls, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  DISTANCE_LABEL, KIND_LABEL, MAIN_KINDS, OPEN_EVENT_EVENT, TYPE_LABEL, countdown, deleteEvent, daysUntil, isRace, isUpcoming, kindOf,
  listEvents, makeMainEvent, nextDate, takeOpenEvent, writeDebrief,
  type Debrief, type EventFields, type EventKind, type EventType, type RaceEvent,
} from '@/lib/events'
import { EventBasics, EventGoal, EventKindFields, InfoBlock, KIND_ICON, KindPicker, kindDefaults } from './EventForm'
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

const TYPE_ICON: Record<EventType, typeof Bike> = {
  triathlon: Layers, duathlon: Layers, running: Footprints, trail: Mountain, cycling: Bike,
  swimming: Waves, mountaineering: Mountain, team_sport: Volleyball, other: Activity,
}

export function EventsScreen({ hasBuiltPlan, onClose, onChanged, onOpenPlan, onBuildPlan, imperial = false }: {
  hasBuiltPlan: boolean
  /** none when it is the Events tab page (no X) */
  onClose?: () => void
  onChanged: () => void
  onOpenPlan: () => void
  onBuildPlan: () => void
  imperial?: boolean
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
  const upcoming = (events ?? []).filter(isUpcoming).sort((a, b) => nextDate(a).localeCompare(nextDate(b)))
  const past = (events ?? []).filter((e) => !isUpcoming(e)).reverse()
  const saved = (list: RaceEvent[]) => { setEvents(list); setChanged(true); onChanged() }

  // "Add" waits for the list: whether a new event becomes the main one depends on it.
  return (
    <>
      <Screen title="Events" subtitle="Races, group sessions, trips and big days" closing={closing} onClose={close}
        footer={<Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" disabled={events === null}
          onClick={() => setEditing('new')}>
          <CalendarPlus className="size-4" /> Add an event</Button>}>
        <PullToRefresh onRefresh={load} disabled={events === null && !error} />
        {events === null && !error ? (
          <EventsSkeleton />
        ) : error ? (
          <p className="px-1 text-[0.8235rem] text-(--danger)">
            {error} <button type="button" className="hit-44 underline" onClick={() => void load()}>Retry</button>
          </p>
        ) : (
          <>
            <RaceInvitesInbox onChanged={() => { void load(); setFollowKey((k) => k + 1) }} />
            {changed && (
              <div className="flex items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5">
                <p className="min-w-0 flex-1 text-[0.7647rem] text-(--accent)">
                  {hasBuiltPlan ? 'Rebuild your plan to fit these changes in.' : 'Build a plan around your main event.'}
                </p>
                <Button variant="primary" className="h-8 px-3 text-[0.7059rem]" onClick={hasBuiltPlan ? onOpenPlan : onBuildPlan}>
                  {hasBuiltPlan ? 'Open plan' : 'Build plan'}
                </Button>
              </div>
            )}
            {upcoming.length === 0 && (
              <EmptyState title="Nothing on the calendar yet"
                body="Add races, group rides, trips and big days. Rabbit plans around all of them."
                action="Add an event" onAction={() => setEditing('new')} />
            )}
            {upcoming.length > 0 && (
              <section className="flex flex-col gap-2">
                {upcoming.map((e, i) => (
                  <HopIn key={e.id} index={i}>
                    <EventCard e={e} grade={grades[e.id]} people={people[e.id]} onPeople={() => setPeopleFor(e)} onClick={() => setEditing(e)}
                      onFit={kindOf(e) === 'milestone' ? undefined : () => setFit(e)}
                      onPack={daysUntil(e.date) <= 21 && kindOf(e) !== 'milestone' ? () => setPack(e) : undefined} />
                  </HopIn>
                ))}
              </section>
            )}
            <FollowingRaces refreshKey={followKey} />
            {past.length > 0 && (
              <section className="flex flex-col gap-2">
                <button type="button" onClick={() => setShowPast((v) => !v)}
                  className="hit-44 flex items-center gap-1 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
                  Past events ({past.length}) <ChevronRight className={cn('size-3.5 transition-transform', showPast && 'rotate-90')} />
                </button>
                {showPast && past.map((e, i) => <HopIn key={e.id} index={i}><EventCard e={e} onClick={() => setEditing(e)} /></HopIn>)}
              </section>
            )}
            <CalendarSync />
            <details className="px-1 text-[0.7059rem] leading-snug text-(--text-muted)">
              <summary className="hit-44 inline-flex min-h-11 cursor-pointer items-center font-medium text-(--text-secondary)">How events shape your plan</summary>
              <p>
                Your <Star className="inline size-3 -translate-y-px fill-current" /> main event is what your plan builds toward.
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
          className="flex min-h-11 w-full items-center gap-1.5 border-t border-(--border) px-3.5 py-2 text-left text-[0.7059rem] font-medium text-(--accent) active:bg-(--bg-inset)">
          <Gauge className="size-3.5" /> Event prep <ChevronRight className="ml-auto size-3.5 text-(--text-muted)" />
        </button>
      ) : grade ? <ReadinessRow g={grade} onClick={onFit} extra={n >= 0 ? <FinishChip eventId={e.id} /> : undefined} /> : (
        <button type="button" onClick={onFit}
          className="flex min-h-11 w-full items-center gap-1.5 border-t border-(--border) px-3.5 py-2 text-left text-[0.7059rem] font-medium text-(--accent) active:bg-(--bg-inset)">
          <Gauge className="size-3.5" /> Readiness & race fit
          <span className="ml-auto flex items-center gap-1.5">
            {n >= 0 && <FinishChip eventId={e.id} />}<ChevronRight className="size-3.5 text-(--text-muted)" />
          </span>
        </button>
      )}
      {onPack && (
        <button type="button" onClick={onPack}
          className="flex min-h-11 w-full items-center gap-1.5 border-t border-(--border) px-3.5 py-2 text-left text-[0.7059rem] font-medium text-(--accent) active:bg-(--bg-inset)">
          <Backpack className="size-3.5" /> {packTitle(kindOf(e))} <ChevronRight className="ml-auto size-3.5 text-(--text-muted)" />
        </button>
      )}
      {onPeople && <PeopleRow s={people} onOpen={onPeople} />}
    </div>
  )
}

function EventCardButton({ e, onClick, bare }: { e: RaceEvent; onClick: () => void; bare?: boolean }) {
  const kind = kindOf(e)
  const Icon = kind === 'race' ? TYPE_ICON[e.type] ?? Activity : e.type === 'team_sport' ? Volleyball : KIND_ICON[kind]
  const when = nextDate(e)
  const n = daysUntil(when)
  return (
    <button type="button" onClick={onClick}
      className={cn('flex w-full items-center gap-3 bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)',
        !bare && 'rounded-xl border', !bare && (e.main ? 'border-(--accent)' : 'border-(--border)'), !bare && !isUpcoming(e) && 'opacity-70')}>
      <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl',
        e.main ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--accent-subtle) text-(--accent)')}>
        <Icon className="size-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          {e.main && <Star className="size-3.5 shrink-0 fill-(--accent) text-(--accent)" aria-label="Main event" />}
          <span className="truncate text-[0.9412rem] font-medium text-(--text)">{e.name}</span>
        </span>
        <span className="block truncate text-[0.7059rem] text-(--text-muted)">
          {e.recurring && e.repeat_text ? `${e.repeat_text}${e.time ? ` · ${e.time}` : ''}`
            : new Date(`${e.date}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}
          {e.end_date && e.end_date !== e.date ? ` – ${new Date(`${e.end_date}T12:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })}` : ''}
          {kind === 'milestone' ? '' : ` · ${TYPE_LABEL[e.type]}`}
          {kind !== 'race' || !e.distance || e.distance === 'other' ? '' : ` · ${DISTANCE_LABEL[e.distance] ?? e.distance}`}
          {e.location ? ` · ${e.location}` : e.at ? ` · ${e.at}` : ''}{e.neighborhood ? ` · ${e.neighborhood}` : ''}
        </span>
        {e.plan && (e.plan.status === 'in_plan' || e.plan.status === 'pending') && (
          <span className={cn('mt-0.5 flex items-center gap-1 text-[0.6471rem] font-medium', e.plan.status === 'in_plan' ? 'text-(--accent)' : 'text-(--warning-text)')}>
            {e.recurring && <Repeat className="size-3" aria-hidden />}{e.plan.status === 'in_plan' ? 'In your plan' : 'Not in your plan yet'}
          </span>
        )}
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1">
        <span className="rounded-full bg-(--bg-elevated) px-2 py-0.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-wider text-(--text-secondary)">
          {e.main ? 'Main' : kind !== 'race' ? KIND_LABEL[kind] : e.priority === 'C' ? 'Training' : `${e.priority} race`}
        </span>
        <span className="text-[0.6471rem] text-(--text-muted)">{e.result && n < 0 ? e.result : e.recurring && isUpcoming(e) ? `Next: ${countdown(when)}` : countdown(when)}</span>
      </span>
    </button>
  )
}

function EventEditor({ event, isFirst, onClose, onSaved, onUpdated, onOpenEvent, onOpenPlan, onBuildPlan, imperial }: {
  event: RaceEvent | null; isFirst: boolean; imperial: boolean
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
      'end_date', 'time', 'recurring', 'with', 'at', 'duration_min', 'intensity', 'neighborhood', 'in_plan'] as const) {
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
    <Screen title={event ? event.name : 'Add an event'} subtitle={event?.main ? 'Your main event' : undefined}
      closing={closing} onClose={guard.wrap(close)} onBack={guard.wrap(close)}
      footer={<>
        <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy === 'save'}
          disabled={!kind || !(v.name ?? '').trim() || !v.date}
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
          {event ? 'Save changes' : 'Add event'}
        </Button>
      </>}>
      {draft.restored && <DraftRestored onDiscard={draft.discard} />}
      {guard.dialog}
      {event?.series_id && (
        <button type="button" onClick={() => onOpenEvent(event.series_id!)}
          className="flex min-h-11 items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 text-left text-[0.7647rem] text-(--text-secondary) active:bg-(--bg-inset)">
          <Repeat className="size-4 text-(--accent)" aria-hidden /> <span className="flex-1">One date of a repeating event</span>
          <span className="font-medium text-(--accent)">See the series</span>
        </button>
      )}
      {event && <EventPlanCard event={event} onOpenPlan={() => { onOpenPlan(); close() }} onBuildPlan={() => { onBuildPlan(); close() }} />}
      {event && !past && <UpcomingDates event={event} onSaved={onUpdated} />}
      {event && !past && <AddToCalendar event={event} />}
      {!event && <KindPicker value={kind} onChange={(k) => setV((x) => ({ ...kindDefaults(k, isFirst), name: x.name, date: x.date, location: x.location }))} />}
      {kind && (<>
      <EventBasics value={v} onChange={set} eventId={event?.id} allowPast={past} />
      <EventKindFields value={v} onChange={set} />
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
        <label className="flex items-center gap-3 px-1 text-[0.8235rem] text-(--text)">
          <input type="checkbox" className="size-4 accent-(--accent)" checked={main} onChange={(e) => setMain(e.target.checked)} />
          Make this my main event (the plan builds toward it)
        </label>
      )}
      {event && !past && kind !== 'milestone' && (
        <div className="flex gap-2">
          <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={() => setPack(true)}>
            <Backpack className="size-4" /> {packTitle(kind)}
          </Button>
          <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={() => setFitOpen(true)}>
            <Gauge className="size-4" /> {race ? 'Readiness' : 'Event prep'}
          </Button>
        </div>
      )}
      {fitOpen && event && <RaceFitScreen eventId={event.id} race={race} onClose={() => setFitOpen(false)} />}
      {pack && event && <RacePackScreen eventId={event.id} kind={kind} imperial={imperial} onClose={() => setPack(false)} />}
      {event && !event.main && !past && canBeMain && (
        <Button variant="default" className="h-11 gap-1.5 text-[0.8235rem]" loading={busy === 'main'}
          onClick={() => void run('main', () => makeMainEvent(event.id))}>
          <Star className="size-4" /> Make this my main event
        </Button>
      )}
      {event && !event.main && (confirmDelete ? (
        <div className="flex items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3">
          <span className="min-w-0 flex-1 text-[0.8235rem]">Delete {event.name}?</span>
          <Button variant="default" className="h-9 px-3 text-[0.7647rem]" onClick={() => setConfirmDelete(false)}>Keep</Button>
          <Button variant="destructive" className="h-9 px-3 text-[0.7647rem]" loading={busy === 'delete'}
            onClick={() => void run('delete', () => deleteEvent(event.id))}>Delete</Button>
        </div>
      ) : (
        <Button variant="ghost" className="h-10 gap-1.5 text-[0.7647rem] text-(--danger)" onClick={() => setConfirmDelete(true)}>
          <Trash2 className="size-4" /> Delete event
        </Button>
      ))}
      {queued && busy === 'save' && <SaveStatus state="queued" className="px-1" />}
      {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
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
      <Field label="Race debrief" hint="Rabbit reads your race from Garmin plus your notes, then saves learnings it carries into your next plan.">
        <div className="flex flex-wrap gap-2">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" onClick={() => setFeel(n)} aria-pressed={feel === n}
              className={cn('plan-chip', feel === n && 'plan-chip--on')}>{['Rough', 'Hard', 'OK', 'Good', 'Great'][n - 1]}</button>
          ))}
        </div>
        <Button variant="primary" className="h-10 text-[0.7647rem]" loading={busy} onClick={() => void write()}>
          {d ? 'Rewrite my debrief' : 'Write my debrief'}
        </Button>
        {error && <p className="text-[0.7059rem] text-(--danger)">{error}</p>}
        {d && (
          <div className="flex flex-col gap-2 rounded-lg bg-(--bg-inset) p-3 text-[0.7647rem] leading-snug">
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
