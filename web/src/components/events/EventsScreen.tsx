// Events: every race on your calendar. Add, edit, look up, delete, and pick the main one
// (the race your plan builds toward). Other races become B/C race days in the plan.
import { useCallback, useEffect, useState } from 'react'
import { Activity, Backpack, Bike, CalendarPlus, ChevronRight, Footprints, Gauge, Layers, Mountain, Star, Trash2, Waves } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Card, Field, Screen, areaCls, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  DISTANCE_LABEL, TYPE_LABEL, countdown, createEvent, deleteEvent, daysUntil, listEvents, makeMainEvent, updateEvent, writeDebrief,
  type Debrief, type EventFields, type EventType, type RaceEvent,
} from '@/lib/events'
import { EventBasics, EventGoal, InfoBlock } from './EventForm'
import { RacePackScreen } from './RacePackScreen'
import { RaceFitScreen } from './RaceFitScreen'

const TYPE_ICON: Record<EventType, typeof Bike> = {
  triathlon: Layers, duathlon: Layers, running: Footprints, trail: Mountain, cycling: Bike,
  swimming: Waves, mountaineering: Mountain, other: Activity,
}

export function EventsScreen({ hasBuiltPlan, onClose, onChanged, onOpenPlan, onBuildPlan, imperial = false }: {
  hasBuiltPlan: boolean
  onClose: () => void
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
  const [fit, setFit] = useState<string | null>(null)

  const load = useCallback(() => {
    setError(null)
    listEvents().then((r) => setEvents(r.events), (e) => setError((e as Error).message))
  }, [])
  useEffect(load, [load])

  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const upcoming = (events ?? []).filter((e) => daysUntil(e.date) >= 0)
  const past = (events ?? []).filter((e) => daysUntil(e.date) < 0).reverse()
  const saved = (list: RaceEvent[]) => { setEvents(list); setChanged(true); onChanged() }

  // "Add" waits for the list: whether a new event becomes the main one depends on it.
  return (
    <>
      <Screen title="Events" subtitle="Races and challenges on your calendar" closing={closing} onClose={close}
        footer={<Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" disabled={events === null}
          onClick={() => setEditing('new')}>
          <CalendarPlus className="size-4" /> Add an event</Button>}>
        {events === null && !error ? (
          <div className="flex justify-center py-16" role="status" aria-label="Loading events">
            <RabbitLogo size={56} thinking className="text-(--brand) opacity-60" />
          </div>
        ) : error ? (
          <p className="px-1 text-[0.8235rem] text-(--danger)">
            {error} <button type="button" className="underline" onClick={load}>Retry</button>
          </p>
        ) : (
          <>
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
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <CalendarPlus className="size-8 text-(--text-muted)" />
                <p className="text-[0.8824rem] text-(--text)">No upcoming events yet</p>
                <p className="max-w-xs text-[0.7647rem] text-(--text-muted)">Add your races, rides and big days. Rabbit plans around all of them.</p>
              </div>
            )}
            {upcoming.length > 0 && (
              <section className="flex flex-col gap-2">
                {upcoming.map((e) => <EventCard key={e.id} e={e} onClick={() => setEditing(e)} onFit={() => setFit(e.id)} />)}
              </section>
            )}
            {past.length > 0 && (
              <section className="flex flex-col gap-2">
                <button type="button" onClick={() => setShowPast((v) => !v)}
                  className="flex items-center gap-1 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
                  Past events ({past.length}) <ChevronRight className={cn('size-3.5 transition-transform', showPast && 'rotate-90')} />
                </button>
                {showPast && past.map((e) => <EventCard key={e.id} e={e} onClick={() => setEditing(e)} />)}
              </section>
            )}
            <p className="px-1 text-[0.7059rem] leading-snug text-(--text-muted)">
              Your <Star className="inline size-3 -translate-y-px fill-current" /> main event is what your plan builds toward.
              Other upcoming races go into the plan as race days: B races get a short taper, training races are raced as hard workouts.
            </p>
          </>
        )}
      </Screen>
      {editing && (
        <EventEditor event={editing === 'new' ? null : editing} isFirst={events !== null && events.length === 0} imperial={imperial}
          onClose={() => setEditing(null)} onSaved={(list) => { saved(list) }} />
      )}
      {fit && <RaceFitScreen eventId={fit} onClose={() => setFit(null)} />}
    </>
  )
}

function EventCard({ e, onClick, onFit }: { e: RaceEvent; onClick: () => void; onFit?: () => void }) {
  const n = daysUntil(e.date)
  if (!onFit) return <EventCardButton e={e} onClick={onClick} />
  return (
    <div className={cn('overflow-hidden rounded-xl border bg-(--bg-surface)', e.main ? 'border-(--accent)' : 'border-(--border)', n < 0 && 'opacity-70')}>
      <EventCardButton e={e} onClick={onClick} bare />
      <button type="button" onClick={onFit}
        className="flex w-full items-center gap-1.5 border-t border-(--border) px-3.5 py-2 text-left text-[0.7059rem] font-medium text-(--accent) active:bg-(--bg-inset)">
        <Gauge className="size-3.5" /> Race fit <ChevronRight className="ml-auto size-3.5 text-(--text-muted)" />
      </button>
    </div>
  )
}

function EventCardButton({ e, onClick, bare }: { e: RaceEvent; onClick: () => void; bare?: boolean }) {
  const Icon = TYPE_ICON[e.type] ?? Activity
  const n = daysUntil(e.date)
  return (
    <button type="button" onClick={onClick}
      className={cn('flex w-full items-center gap-3 bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)',
        !bare && 'rounded-xl border', !bare && (e.main ? 'border-(--accent)' : 'border-(--border)'), !bare && n < 0 && 'opacity-70')}>
      <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl',
        e.main ? 'bg-(--accent) text-white' : 'bg-(--accent-subtle) text-(--accent)')}>
        <Icon className="size-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          {e.main && <Star className="size-3.5 shrink-0 fill-(--accent) text-(--accent)" aria-label="Main event" />}
          <span className="truncate text-[0.9412rem] font-medium text-(--text)">{e.name}</span>
        </span>
        <span className="block truncate text-[0.7059rem] text-(--text-muted)">
          {new Date(`${e.date}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}
          {' · '}{TYPE_LABEL[e.type]}{e.distance && e.distance !== 'other' ? ` · ${DISTANCE_LABEL[e.distance] ?? e.distance}` : ''}
          {e.location ? ` · ${e.location}` : ''}
        </span>
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1">
        <span className="rounded-full bg-(--bg-elevated) px-2 py-0.5 font-mono text-[0.5882rem] font-semibold uppercase tracking-wider text-(--text-secondary)">
          {e.main ? 'Main' : e.priority === 'C' ? 'Training' : `${e.priority} race`}
        </span>
        <span className="text-[0.6471rem] text-(--text-muted)">{e.result && n < 0 ? e.result : countdown(e.date)}</span>
      </span>
    </button>
  )
}

function EventEditor({ event, isFirst, onClose, onSaved, imperial }: {
  event: RaceEvent | null; isFirst: boolean; imperial: boolean
  onClose: () => void; onSaved: (list: RaceEvent[]) => void
}) {
  const [closing, setClosing] = useState(false)
  const [v, setV] = useState<EventFields>(() => event ? { ...event } : { type: 'triathlon', distance: '70.3', priority: isFirst ? 'A' : 'B', goal_type: 'finish' })
  const [main, setMain] = useState(isFirst)
  const [busy, setBusy] = useState<'save' | 'delete' | 'main' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [pack, setPack] = useState(false)
  const [fitOpen, setFitOpen] = useState(false)
  const set = (p: EventFields) => setV((x) => ({ ...x, ...p }))
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const past = !!event && daysUntil(event.date) < 0

  async function run(kind: 'save' | 'delete' | 'main', fn: () => Promise<{ events: RaceEvent[] }>) {
    setBusy(kind); setError(null)
    try { const r = await fn(); onSaved(r.events); close() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }

  function payload(): EventFields {
    const f: EventFields = {}
    for (const k of ['name', 'type', 'distance', 'date', 'location', 'url', 'priority', 'goal_type', 'target_time', 'course', 'notes', 'result', 'info', 'elevation_m', 'course_profile'] as const) {
      if (v[k] !== undefined && (!event || v[k] !== event[k])) (f as Record<string, unknown>)[k] = v[k]
    }
    if (f.goal_type !== undefined && f.goal_type !== 'time' && !event?.target_time) delete f.target_time
    if (v.goal_type !== 'time' && event?.target_time) f.target_time = null
    return f
  }

  return (
    <Screen title={event ? event.name : 'Add an event'} subtitle={event?.main ? 'Your main event' : undefined}
      closing={closing} onClose={close} onBack={close}
      footer={<>
        <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" loading={busy === 'save'}
          disabled={!(v.name ?? '').trim() || !v.date}
          onClick={() => void run('save', () => event ? updateEvent(event.id, payload()) : createEvent({ ...payload(), main }))}>
          {event ? 'Save changes' : 'Add event'}
        </Button>
      </>}>
      <EventBasics value={v} onChange={set} eventId={event?.id} allowPast={past} />
      {v.info && <Card className="p-4"><InfoBlock info={v.info} /></Card>}
      <EventGoal value={v} onChange={set} hidePriority={event?.main} imperial={imperial} />
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
      {event && past && <DebriefCard event={event} result={v.result ?? ''} notes={v.notes ?? ''} onSaved={(list) => onSaved(list)} />}
      {!event && !isFirst && (
        <label className="flex items-center gap-3 px-1 text-[0.8235rem] text-(--text)">
          <input type="checkbox" className="size-4 accent-(--accent)" checked={main} onChange={(e) => setMain(e.target.checked)} />
          Make this my main event (the plan builds toward it)
        </label>
      )}
      {event && !past && (
        <div className="flex gap-2">
          <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={() => setPack(true)}>
            <Backpack className="size-4" /> Race-week pack
          </Button>
          <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={() => setFitOpen(true)}>
            <Gauge className="size-4" /> Race fit
          </Button>
        </div>
      )}
      {fitOpen && event && <RaceFitScreen eventId={event.id} onClose={() => setFitOpen(false)} />}
      {pack && event && <RacePackScreen eventId={event.id} imperial={imperial} onClose={() => setPack(false)} />}
      {event && !event.main && !past && (
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
            {d.work_on.length > 0 && <p><b className="text-(--warning)">Work on:</b> <span className="text-(--text-secondary)">{d.work_on.join('; ')}</span></p>}
            {d.learnings.length > 0 && <p><b className="text-(--text)">For your next plan:</b> <span className="text-(--text-secondary)">{d.learnings.join('; ')}</span></p>}
          </div>
        )}
      </Field>
    </Card>
  )
}
