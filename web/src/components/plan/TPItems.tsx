// TrainingPeaks on the plan calendar (server: tpsync.py). Planned TrainingPeaks workouts show
// next to Rabbit's sessions tagged "From TrainingPeaks"; when both plans have the same workout
// only the source of truth's copy shows (`hide_sessions` / `item.show`). Tapping one opens its
// details (coach notes, structure, the linked Garmin workout) and lets the athlete move it,
// which moves it in TrainingPeaks too. With no Rabbit plan, TPCalendarList is the calendar.
import { useCallback, useEffect, useState } from 'react'
import { Activity, Bike, CalendarDays, Check, ClipboardList, Dumbbell, Flag, Footprints, Layers, RefreshCw, TriangleAlert, Waves } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { Card, Field, inputCls } from './ui'
import { fmtDay, todayStr } from './PlanParts'
import { fmtDist, fmtDuration } from '@/lib/format'
import { requestConnect } from '@/lib/connections'
import { cn } from '@/lib/utils'
import {
  TP_CHANGED, TP_SOURCE_LABEL, getTP, moveTP, syncTP, type TPItem, type TPView,
} from '@/lib/trainingpeaks'

const ICON: Record<string, typeof Bike> = {
  swim: Waves, bike: Bike, run: Footprints, brick: Layers, strength: Dumbbell, race: Flag,
}

export type TPState = {
  view: TPView | null
  open: TPItem | null
  setOpen: (it: TPItem | null) => void
  reload: () => void
  /** a Rabbit session hidden because TrainingPeaks (the source) has the same workout */
  hidden: (sessionId: string) => boolean
  itemsOn: (date: string) => TPItem[]
}

/** TrainingPeaks state for a plan screen; null view = not connected (renders nothing). */
export function useTrainingPeaks(enabled: boolean): TPState {
  const [view, setView] = useState<TPView | null>(null)
  const [open, setOpen] = useState<TPItem | null>(null)
  const reload = useCallback(() => {
    if (!enabled) return
    getTP().then((v) => setView(v.connected ? v : null), () => {})
  }, [enabled])
  useEffect(() => {
    reload()
    window.addEventListener(TP_CHANGED, reload)
    return () => window.removeEventListener(TP_CHANGED, reload)
  }, [reload])
  return {
    view, open, setOpen, reload,
    hidden: (sid) => !!view?.hide_sessions.includes(sid),
    itemsOn: (date) => view?.items.filter((i) => i.date === date && i.show) ?? [],
  }
}

function meta(it: TPItem, imperial: boolean): string {
  return [it.minutes ? fmtDuration(it.minutes) : '', it.distance_km ? fmtDist(it.distance_km, imperial, it.sport) : '']
    .filter(Boolean).join(' · ')
}

/** One TrainingPeaks workout as a session-like line with a "TrainingPeaks" tag. */
export function TPLine({ it, imperial, onClick }: { it: TPItem; imperial: boolean; onClick: () => void }) {
  const Icon = ICON[it.sport] ?? Activity
  const m = meta(it, imperial)
  return (
    <button type="button" onClick={onClick} className="flex min-h-11 w-full items-center gap-2.5 py-1.5 text-left">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-(--bg-inset) text-(--text-secondary)">
        <Icon className="size-3.5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[0.8235rem] text-(--text)">{it.title}</span>
        <span className="block truncate text-[0.6471rem] text-(--text-muted)">
          From TrainingPeaks{m ? ` · ${m}` : ''}{it.coach_notes ? ' · coach notes' : ''}
        </span>
      </span>
      {it.garmin_activity_id
        ? <span className="flex shrink-0 items-center gap-1 rounded-full bg-(--accent-subtle) px-2 py-0.5 text-[0.6471rem] text-(--accent)"><Check className="size-3" aria-hidden />Done</span>
        : <ClipboardList className="size-3.5 shrink-0 text-(--text-muted)" aria-label="TrainingPeaks" />}
    </button>
  )
}

/** A day's TrainingPeaks workouts inside the plan editor's day row. */
export function TPDayItems({ tp, date, imperial }: { tp: TPState; date: string; imperial: boolean }) {
  const items = tp.itemsOn(date)
  if (!items.length) return null
  return <>{items.map((it) => <TPLine key={it.id} it={it} imperial={imperial} onClick={() => tp.setOpen(it)} />)}</>
}

/** Status line above the week: source, last sync, Sync now; "Needs attention" -> reconnect. */
export function TPPlanBar({ tp, onToast }: { tp: TPState; onToast?: (m: string) => void }) {
  const [busy, setBusy] = useState(false)
  const v = tp.view
  if (!v) return null
  const attention = v.state === 'attention'
  async function sync() {
    setBusy(true)
    try {
      const r = await syncTP()
      tp.reload()
      onToast?.(r.result.ok ? 'TrainingPeaks synced' : r.result.error ?? 'Couldn’t sync TrainingPeaks')
    } catch (e) { onToast?.((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className={cn('flex items-center gap-2.5 rounded-xl border px-3.5 py-2', attention ? 'border-(--warning-text)' : 'border-(--border)')}>
      {attention ? <TriangleAlert className="size-4 shrink-0 text-(--warning-text)" aria-hidden />
        : <ClipboardList className="size-4 shrink-0 text-(--text-muted)" aria-hidden />}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[0.7647rem] text-(--text)">TrainingPeaks · {TP_SOURCE_LABEL[v.source]} leads</span>
        <span className={cn('block text-[0.6471rem] leading-snug', attention || v.error ? 'text-(--warning-text)' : 'text-(--text-muted)')}>
          {v.error ?? (v.last_sync ? `Synced ${new Date(v.last_sync * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}` : 'Not synced yet')}
        </span>
      </span>
      {attention ? (
        <Button variant="primary" className="h-11 px-3 text-[0.7647rem]" onClick={() => requestConnect('trainingpeaks')}>Reconnect</Button>
      ) : (
        <button type="button" aria-label="Sync TrainingPeaks now" disabled={busy} onClick={() => void sync()}
          className="hit-44 flex size-8 shrink-0 items-center justify-center rounded-full text-(--text-secondary) active:bg-(--bg-inset)">
          <RefreshCw className={cn('size-4', busy && 'animate-spin motion-reduce:animate-none')} />
        </button>
      )}
    </div>
  )
}

/** The calendar when there's no Rabbit plan: TrainingPeaks workouts by day, today on. */
export function TPCalendarList({ tp, today, imperial }: { tp: TPState; today: string; imperial: boolean }) {
  const v = tp.view
  if (!v) return null
  const items = v.items.filter((i) => i.date >= today)
  const days = [...new Set(items.map((i) => i.date))]
  return (
    <section className="flex w-full flex-col gap-2 text-left">
      <TPPlanBar tp={tp} />
      {days.length ? (
        <Card>
          <div className="divide-y divide-(--border)">
            {days.map((d) => (
              <div key={d} className="flex gap-3 px-4 py-2">
                <span className="w-10 shrink-0 pt-2 text-center leading-tight">
                  <span className="block text-[0.6471rem] font-semibold uppercase text-(--text-muted)">{fmtDay(d, { weekday: 'short' })}</span>
                  <span className="block text-[0.7647rem] text-(--text-secondary)">{fmtDay(d, { day: 'numeric' })}</span>
                </span>
                <div className="min-w-0 flex-1">
                  {items.filter((i) => i.date === d).map((it) => <TPLine key={it.id} it={it} imperial={imperial} onClick={() => tp.setOpen(it)} />)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <p className="px-1 text-[0.7647rem] text-(--text-muted)">Nothing planned in TrainingPeaks for the next 6 weeks.</p>
      )}
    </section>
  )
}

/** Details + move. Rendered once per screen; opens when `tp.open` is set. */
export function TPWorkoutSheet({ tp, today, imperial, onToast }: {
  tp: TPState; today: string; imperial: boolean; onToast?: (m: string) => void
}) {
  const it = tp.open
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setDate(it?.date ?? ''); setErr(null) }, [it])
  if (!it) return null
  const m = meta(it, imperial)
  const close = () => tp.setOpen(null)

  async function move() {
    if (!it || !date || date === it.date) return
    setBusy(true); setErr(null)
    try {
      await moveTP(it.id, date)
      tp.reload()
      onToast?.(`Moved to ${fmtDay(date)} in TrainingPeaks too`)
      close()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <Sheet title={it.title} onClose={close} dismissible={!busy} bodyClassName="gap-3.5" portal>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7647rem] text-(--text-secondary)">
        <span className="inline-flex items-center gap-1 rounded-full bg-(--bg-inset) px-2 py-0.5 text-[0.6471rem] text-(--text-secondary)">
          <ClipboardList className="size-3" aria-hidden />From TrainingPeaks
        </span>
        <span><CalendarDays className="mr-1 inline size-3.5 align-[-2px]" aria-hidden />{fmtDay(it.date)}</span>
        {m && <span>· {m}</span>}
      </p>
      {it.garmin_activity_id && (
        <p className="flex items-center gap-2 rounded-xl bg-(--accent-subtle) px-3.5 py-2.5 text-[0.7647rem] text-(--accent)">
          <Check className="size-4 shrink-0" aria-hidden />Done: matched to your Garmin workout that day.
        </p>
      )}
      {it.coach_notes && (
        <section className="flex flex-col gap-1">
          <h2 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Coach notes</h2>
          <p className="whitespace-pre-line text-[0.8235rem] leading-snug text-(--text)">{it.coach_notes}</p>
        </section>
      )}
      {it.description && (
        <section className="flex flex-col gap-1">
          <h2 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Description</h2>
          <p className="whitespace-pre-line text-[0.8235rem] leading-snug text-(--text-secondary)">{it.description}</p>
        </section>
      )}
      {it.structure.length > 0 && (
        <section className="flex flex-col gap-1">
          <h2 className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Structure</h2>
          <ul className="flex flex-col gap-0.5 text-[0.7647rem] text-(--text-secondary)">
            {it.structure.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </section>
      )}
      {it.can_move ? (
        <Field label="Move to">
          <div className="flex gap-2">
            <input type="date" className={inputCls} min={today} value={date} onChange={(e) => setDate(e.target.value)} aria-label="New date" />
            <Button variant="primary" className="h-10 shrink-0 px-4 text-[0.8235rem]" loading={busy}
              disabled={!date || date === it.date || date < today} onClick={() => void move()}>Move</Button>
          </div>
        </Field>
      ) : (
        <p className="text-[0.7059rem] leading-snug text-(--text-muted)">
          {it.completed ? 'This workout is done, so it stays where it is.'
            : 'This one follows your Rabbit plan: move the workout in Rabbit and TrainingPeaks follows.'}
        </p>
      )}
      {err && <p role="alert" className="text-[0.7647rem] text-(--danger)">{err}</p>}
    </Sheet>
  )
}

/** The Plan tab without a Rabbit plan: the TrainingPeaks calendar on its own (nothing when
 * TrainingPeaks isn't connected). */
export function TPPlanSection({ imperial }: { imperial: boolean }) {
  const tp = useTrainingPeaks(true)
  if (!tp.view) return null
  const today = todayStr()
  return (
    <>
      <TPCalendarList tp={tp} today={today} imperial={imperial} />
      <TPWorkoutSheet tp={tp} today={today} imperial={imperial} />
    </>
  )
}
