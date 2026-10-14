// Events: every race on your calendar. Add, edit, look up, delete, and pick the main one
// (the race your plan builds toward). Other races become B/C race days in the plan.
import { useCallback, useEffect, useState } from 'react'
import { Activity, Bike, CalendarPlus, ChevronRight, Footprints, Layers, Mountain, Star, Trash2, Waves } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Card, Field, Screen, areaCls, inputCls } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  DISTANCE_LABEL, TYPE_LABEL, countdown, createEvent, deleteEvent, daysUntil, listEvents, makeMainEvent, updateEvent,
  type EventFields, type EventType, type RaceEvent,
} from '@/lib/events'
import { EventBasics, EventGoal, InfoBlock } from './EventForm'

const TYPE_ICON: Record<EventType, typeof Bike> = {
  triathlon: Layers, duathlon: Layers, running: Footprints, trail: Mountain, cycling: Bike,
  swimming: Waves, mountaineering: Mountain, other: Activity,
}

export function EventsScreen({ hasBuiltPlan, onClose, onChanged, onOpenPlan, onBuildPlan, startAdding }: {
  hasBuiltPlan: boolean
  onClose: () => void
  onChanged: () => void
  onOpenPlan: () => void
  onBuildPlan: () => void
  startAdding?: boolean
}) {
  const [events, setEvents] = useState<RaceEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [editing, setEditing] = useState<RaceEvent | 'new' | null>(startAdding ? 'new' : null)
  const [showPast, setShowPast] = useState(false)
  const [changed, setChanged] = useState(false)

  const load = useCallback(() => {
    listEvents().then((r) => setEvents(r.events), (e) => setError((e as Error).message))
  }, [])
  useEffect(load, [load])

  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  const upcoming = (events ?? []).filter((e) => daysUntil(e.date) >= 0)
  const past = (events ?? []).filter((e) => daysUntil(e.date) < 0).reverse()
  const saved = (list: RaceEvent[]) => { setEvents(list); setChanged(true); onChanged() }

  return (
    <>
      <Screen title="Events" subtitle="Races and challenges on your calendar" closing={closing} onClose={close}
        footer={<Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" onClick={() => setEditing('new')}>
          <CalendarPlus className="size-4" /> Add an event</Button>}>
        {events === null && !error ? (
          <div className="flex justify-center py-16" role="status" aria-label="Loading events">
            <RabbitLogo size={56} thinking className="text-(--brand) opacity-60" />
          </div>
        ) : error ? (
          <p className="px-1 text-[0.8235rem] text-(--danger)">{error}</p>
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
                {upcoming.map((e) => <EventCard key={e.id} e={e} onClick={() => setEditing(e)} />)}
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
        <EventEditor event={editing === 'new' ? null : editing} isFirst={(events ?? []).length === 0}
          onClose={() => setEditing(null)} onSaved={(list) => { saved(list) }} />
      )}
    </>
  )
}

function EventCard({ e, onClick }: { e: RaceEvent; onClick: () => void }) {
  const Icon = TYPE_ICON[e.type] ?? Activity
  const n = daysUntil(e.date)
  return (
    <button type="button" onClick={onClick}
      className={cn('flex w-full items-center gap-3 rounded-xl border bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)',
        e.main ? 'border-(--accent)' : 'border-(--border)', n < 0 && 'opacity-70')}>
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

function EventEditor({ event, isFirst, onClose, onSaved }: {
  event: RaceEvent | null; isFirst: boolean
  onClose: () => void; onSaved: (list: RaceEvent[]) => void
}) {
  const [closing, setClosing] = useState(false)
  const [v, setV] = useState<EventFields>(() => event ? { ...event } : { type: 'triathlon', distance: '70.3', priority: isFirst ? 'A' : 'B', goal_type: 'finish' })
  const [main, setMain] = useState(isFirst)
  const [busy, setBusy] = useState<'save' | 'delete' | 'main' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
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
    for (const k of ['name', 'type', 'distance', 'date', 'location', 'url', 'priority', 'goal_type', 'target_time', 'course', 'notes', 'result', 'info'] as const) {
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
      <EventGoal value={v} onChange={set} hidePriority={event?.main} />
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
      {!event && !isFirst && (
        <label className="flex items-center gap-3 px-1 text-[0.8235rem] text-(--text)">
          <input type="checkbox" className="size-4 accent-(--accent)" checked={main} onChange={(e) => setMain(e.target.checked)} />
          Make this my main event (the plan builds toward it)
        </label>
      )}
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
