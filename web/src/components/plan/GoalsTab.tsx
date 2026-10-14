// Profile > Goals: every upcoming event (main first, then B and C races) with its goal and
// target time, editable in place, plus a one-line season goal. Full editing lives in Events.
import { useCallback, useEffect, useState } from 'react'
import { CalendarDays, ChevronRight, Star } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import { countdown, daysUntil, listEvents, updateEvent, type RaceEvent } from '@/lib/events'
import { Card, Choice, Field, inputCls } from './ui'

const GOAL_TYPES = [['finish', 'Finish'], ['time', 'Time'], ['compete', 'Compete']] as const
const TIME_RE = /^\d{1,2}:[0-5]\d(:[0-5]\d)?$/

function rank(e: RaceEvent): number {
  return e.main ? 0 : e.priority === 'A' ? 1 : e.priority === 'B' ? 2 : 3
}

export function GoalsTab({ seasonGoal, onSeasonGoal, onOpenEvents }: {
  seasonGoal: string; onSeasonGoal: (v: string) => void; onOpenEvents?: () => void
}) {
  const [events, setEvents] = useState<RaceEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    listEvents().then((r) => setEvents(r.events), (e) => setError((e as Error).message))
  }, [])
  useEffect(load, [load])
  const upcoming = (events ?? []).filter((e) => daysUntil(e.date) >= 0)
    .sort((x, y) => rank(x) - rank(y) || x.date.localeCompare(y.date))

  return (
    <>
      <Card>
        <Field label="Season goal" hint="One line for the whole season. Save to keep it.">
          <input className={inputCls} value={seasonGoal} maxLength={140} placeholder="e.g. Finish Leadville and stay injury-free"
            onChange={(e) => onSeasonGoal(e.target.value)} />
        </Field>
      </Card>
      {events === null && !error && <RabbitLoader size={40} className="py-8" label="Loading events…" />}
      {error && <p className="px-1 text-[0.7647rem] text-(--danger)">{error} <button type="button" className="underline" onClick={load}>Retry</button></p>}
      {events !== null && upcoming.length === 0 && (
        <p className="px-1 text-[0.8235rem] text-(--text-muted)">No upcoming events. Add your races in Events.</p>
      )}
      {upcoming.map((e) => <GoalRow key={e.id} e={e} onSaved={(list) => setEvents(list)} />)}
      {onOpenEvents && (
        <Button variant="default" className="h-11 gap-1.5 text-[0.8235rem]" onClick={onOpenEvents}>
          <CalendarDays className="size-4" /> Edit events <ChevronRight className="size-4" />
        </Button>
      )}
    </>
  )
}

function GoalRow({ e, onSaved }: { e: RaceEvent; onSaved: (list: RaceEvent[]) => void }) {
  const [target, setTarget] = useState(e.target_time ?? '')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  useEffect(() => { setTarget(e.target_time ?? '') }, [e.target_time])

  async function save(patch: Parameters<typeof updateEvent>[1]) {
    setBusy(true); setMsg(null)
    try { const r = await updateEvent(e.id, patch); onSaved(r.events); setMsg({ text: 'Saved', ok: true }) }
    catch (err) { setMsg({ text: (err as Error).message, ok: false }) }
    finally { setBusy(false) }
  }

  function saveTarget() {
    const t = target.trim()
    if (t === (e.target_time ?? '')) return
    if (t && !TIME_RE.test(t)) { setMsg({ text: 'Use h:mm:ss or mm:ss, like 5:30:00.', ok: false }); return }
    void save({ target_time: t || null })
  }

  return (
    <Card className={cn(e.main && 'border-(--accent)')}>
      <div className="flex items-center gap-2 px-4 pt-3.5">
        {e.main && <Star className="size-3.5 shrink-0 fill-(--accent) text-(--accent)" aria-label="Main event" />}
        <span className="min-w-0 flex-1 truncate text-[0.9412rem] font-medium text-(--text)">{e.name}</span>
        <span className="shrink-0 rounded-full bg-(--bg-elevated) px-2 py-0.5 font-mono text-[0.5882rem] font-semibold uppercase tracking-wider text-(--text-secondary)">
          {e.main ? 'Main' : e.priority === 'C' ? 'Training' : `${e.priority} race`}
        </span>
        <span className="shrink-0 text-[0.6471rem] text-(--text-muted)">{countdown(e.date)}</span>
      </div>
      <div className="flex flex-col gap-2 px-4 pb-3.5 pt-2.5">
        <Choice value={e.goal_type ?? 'finish'} options={GOAL_TYPES}
          onChange={(v) => v && v !== e.goal_type && void save(v === 'time' ? { goal_type: v } : { goal_type: v, target_time: null })} />
        {e.goal_type === 'time' && (
          <input className={inputCls} inputMode="numeric" placeholder="Target time, e.g. 5:30:00" aria-label={`Target time for ${e.name}`}
            value={target} onChange={(ev) => setTarget(ev.target.value)} onBlur={saveTarget} disabled={busy} />
        )}
        {msg && <span className={cn('text-[0.7059rem]', msg.ok ? 'text-(--accent)' : 'text-(--danger)')} role="status">{msg.text}</span>}
      </div>
    </Card>
  )
}
