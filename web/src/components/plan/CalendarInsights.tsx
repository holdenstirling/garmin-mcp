// "Your week vs your calendar" (server: calinsights.py) on Schedule > Plan: the next 7 days'
// calendar load as dots, then up to 3 recommendations, each with one action and "Not now".
// Time / move / ease apply on tap (with Undo); travel opens Travel mode with the trip's dates;
// long day opens Adjust my plan. Not connected: one prompt to connect Google Calendar (hidden 30
// days after "Not now"). Also: DayLoadChip for Week / List day rows (busy and packed days).
import { useState } from 'react'
import { CalendarClock, ChevronDown, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SectionLabel } from '@/components/ui/brand'
import { requestConnect } from '@/lib/connections'
import { haptic } from '@/lib/haptics'
import { cn } from '@/lib/utils'
import type { BuiltPlan } from '@/lib/plan'
import {
  LOAD_LABEL, applyCalRec, calPromptHidden, dismissCalRec, hideCalPrompt, undoCalRec,
  type CalDay, type CalInsights, type CalLoad, type CalRec,
} from '@/lib/calinsights'

const DOT: Record<CalLoad, string> = {
  light: 'bg-(--accent)/25', normal: 'bg-(--accent)/55', heavy: 'bg-(--warning-text)/70', packed: 'bg-(--danger)/75',
}
const WD = ['S', 'M', 'T', 'W', 'T', 'F', 'S']

function hours(min: number) {
  if (min < 60) return `${min} min`
  const h = Math.round(min / 30) / 2
  return `${h} h`
}

function LoadDots({ days }: { days: CalDay[] }) {
  return (
    <ol className="flex items-end justify-between gap-1" aria-label="Your calendar, the next 7 days">
      {days.slice(0, 7).map((d) => {
        const dt = new Date(`${d.date}T12:00:00`)
        return (
          <li key={d.date} className="flex flex-1 flex-col items-center gap-1"
            aria-label={`${dt.toLocaleDateString([], { weekday: 'long' })}: ${d.travel ? 'travelling' : `${LOAD_LABEL[d.load]}, ${hours(d.busy_min)} of meetings`}`}>
            <span aria-hidden className={cn('size-3 rounded-full', d.travel ? 'border-2 border-(--accent) bg-transparent' : DOT[d.load])} />
            <span aria-hidden className="text-[0.6471rem] font-medium text-(--text-muted)">{WD[dt.getDay()]}</span>
          </li>
        )
      })}
    </ol>
  )
}

export function CalendarInsightsCard({ data, onApplied, onTravel, onAdjust, onReload }: {
  data: CalInsights | null
  onApplied: (plan: BuiltPlan) => void
  onTravel: (t: { start: string; end: string; label: string }) => void
  onAdjust: () => void
  onReload: () => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [undo, setUndo] = useState<{ id: string; text: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [more, setMore] = useState(false)
  const [promptGone, setPromptGone] = useState(calPromptHidden)

  if (!data) return null
  if (!data.connected) {
    if (!data.available || promptGone) return null
    return (
      <section aria-label="Connect your calendar" className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
        <CalendarClock className="size-5 shrink-0 text-(--accent)" aria-hidden />
        <p className="min-w-0 flex-1 text-[0.7647rem] leading-snug text-(--text-secondary)">
          Connect Google Calendar so rabbt plans around your week.
        </p>
        <div className="flex shrink-0 flex-col gap-1">
          <Button variant="primary" className="h-9 px-3 text-[0.7059rem]" onClick={() => requestConnect('calendar')}>Connect</Button>
          <button type="button" className="hit-44 text-[0.7059rem] text-(--text-muted)" onClick={() => { hideCalPrompt(); setPromptGone(true) }}>Not now</button>
        </div>
      </section>
    )
  }

  const recs = data.recs.filter((r) => !hidden.has(r.id))
  const shown = more ? recs : recs.slice(0, 3)
  const week = data.days.slice(0, 7)
  const packed = week.filter((d) => d.load === 'packed' || d.load === 'heavy').length

  async function act(r: CalRec) {
    setErr(null)
    if (r.action.type === 'travel') { onTravel({ start: r.action.start, end: r.action.end, label: r.action.name }); return }
    if (r.action.type === 'long_day') { onAdjust(); return }
    setBusy(r.id)
    try {
      const out = await applyCalRec(r.id)
      haptic()
      setHidden((h) => new Set(h).add(r.id))
      onApplied(out.plan)
      if (out.undo) setUndo({ id: out.undo, text: r.kind === 'move' ? 'Moved.' : r.kind === 'ease' ? 'Made it easy.' : 'Start time set.' })
      onReload()
    } catch (e) { setErr((e as Error).message); onReload() } finally { setBusy(null) }
  }
  async function notNow(r: CalRec) {
    setHidden((h) => new Set(h).add(r.id))
    await dismissCalRec(r.id).catch(() => undefined)
  }
  async function doUndo() {
    if (!undo) return
    setBusy('undo')
    try { const out = await undoCalRec(undo.id); onApplied(out.plan); setUndo(null); onReload() }
    catch (e) { setErr((e as Error).message); setUndo(null) } finally { setBusy(null) }
  }

  return (
    <section aria-label="Your week vs your calendar" className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
      <div className="flex items-center gap-2">
        <CalendarClock className="size-4 text-(--accent)" aria-hidden />
        <SectionLabel as="h3" className="flex-1 px-0">Your week vs your calendar</SectionLabel>
      </div>
      {week.length > 0 && <LoadDots days={week} />}
      {data.error && <p className="text-[0.7059rem] text-(--text-muted)">{data.error}</p>}
      {!data.error && recs.length === 0 && (
        <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">
          {packed ? `${packed} busy day${packed === 1 ? '' : 's'} this week, and your plan already fits around them.` : 'Your plan and your calendar line up this week.'}
        </p>
      )}
      <ul className="flex flex-col gap-2" aria-live="polite">
        {shown.map((r) => (
          <li key={r.id} className="flex flex-col gap-2 rounded-lg bg-(--bg-inset) px-3 py-2.5">
            <p className="m-0 text-[0.8235rem] font-semibold leading-snug text-(--text)">{r.title}</p>
            <p className="m-0 text-[0.7647rem] leading-snug text-(--text-secondary)">{r.body}</p>
            <div className="flex items-center gap-2">
              <Button variant="primary" className="h-10 px-3.5 text-[0.7647rem]" loading={busy === r.id} disabled={!!busy && busy !== r.id}
                onClick={() => void act(r)}>{r.label}</Button>
              <button type="button" className="hit-44 px-2 text-[0.7647rem] text-(--text-muted)" onClick={() => void notNow(r)}>Not now</button>
            </div>
          </li>
        ))}
      </ul>
      {recs.length > 3 && (
        <button type="button" className="hit-44 inline-flex items-center gap-1 self-start text-[0.7647rem] text-(--accent)" aria-expanded={more}
          onClick={() => setMore((m) => !m)}>
          {more ? 'Show less' : `${recs.length - 3} more`} <ChevronDown className={cn('size-3.5 transition-transform', more && 'rotate-180')} aria-hidden />
        </button>
      )}
      {undo && (
        <div className="flex items-center gap-2 text-[0.7647rem] text-(--accent)" role="status">
          <span className="flex-1">{undo.text}</span>
          <Button variant="default" className="h-9 gap-1 px-3 text-[0.7059rem]" loading={busy === 'undo'} onClick={() => void doUndo()}>
            <Undo2 className="size-3.5" aria-hidden /> Undo
          </Button>
        </div>
      )}
      {err && <p className="text-[0.7059rem] text-(--danger)" role="alert">{err}</p>}
    </section>
  )
}

/** Busy / packed / travel marker for a day row in Week and List views. */
export function DayLoadChip({ day }: { day: CalDay | undefined }) {
  if (!day || (!day.travel && day.load !== 'heavy' && day.load !== 'packed')) return null
  const text = day.travel ? 'Travelling' : `${LOAD_LABEL[day.load]} day · ${hours(day.busy_min)} of meetings`
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-(--bg-inset) px-2 py-0.5 text-[0.6471rem] font-medium text-(--text-secondary)">
      <span aria-hidden className={cn('size-2 rounded-full', day.travel ? 'border border-(--accent)' : DOT[day.load])} />
      {text}
    </span>
  )
}
