// Post-workout reaction (server: workoutday.py): shown once after live sync finds a new
// workout. Verdict badge and planned vs actual first, then XP and streak, PR ribbon, gear mileage, a
// "How did it feel?" check-in and tomorrow's session. Deterministic, no AI.
import { useEffect, useRef, useState } from 'react'
import { Award, CalendarClock, Check, ChevronRight, CirclePlus, Flame, Footprints, Moon, Shuffle, Target, X } from 'lucide-react'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { fmtDay } from '@/components/plan/PlanParts'
import { fmtDuration, fmtMeters } from '@/lib/format'
import { cn } from '@/lib/utils'
import { burst, useCountUp } from '@/components/anim'
import { ShareWorkoutButton } from '@/components/community/ShareWorkout'
import { openActivity } from '@/lib/activitynav'
import { fmtDist, getReaction, type CheckInRequest, type Reaction, type Verdict } from '@/lib/workout'

const LOADING = ['Studying your splits…', 'Comparing to plan…', 'Counting your XP…']
const BADGE: Record<Verdict, { label: string; icon: typeof Check; cls: string }> = {
  nailed: { label: 'Nailed it', icon: Check, cls: 'bg-(--accent) text-(--on-fill)' },
  close: { label: 'Close', icon: Target, cls: 'bg-(--accent-subtle) text-(--accent) border border-(--accent)/40' },
  different: { label: 'Swapped it', icon: Shuffle, cls: 'bg-(--warning-subtle) text-(--warning-text) border border-(--warning)/40' },
  bonus: { label: 'Bonus workout', icon: CirclePlus, cls: 'bg-(--brand) text-(--on-fill)' },
}

export function ReactionCard({ activityId, imperial, onClose, onCheckIn, onOpenSession }: {
  activityId: number
  imperial: boolean
  onClose: () => void
  onCheckIn?: (p: CheckInRequest) => void
  /** open tomorrow's session (the pre-workout screen) */
  onOpenSession?: (sessionId: string) => void
}) {
  const [r, setR] = useState<Reaction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const drag = useSheetDrag(onClose)
  useEffect(() => {
    let live = true
    getReaction(activityId).then((x) => { if (live) setR(x) }, (e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [activityId])
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }

  return (
    <div className={`modal-overlay ${closing ? 'modal-overlay--exit' : ''}`} onClick={close}>
      <div className={`modal ${closing ? 'modal--exit' : ''}`} onClick={(e) => e.stopPropagation()} {...drag}
        role="dialog" aria-modal aria-label="Workout reaction">
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 className="modal-title">{r ? r.activity.name : 'Workout synced'}</h2>
          <button className="modal-close" aria-label="Close" onClick={close}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {!r && !error && <RabbitLoader className="py-10" label="Loading your workout" cycle={LOADING} />}
          {error && <p className="py-8 text-center text-[0.8235rem] text-(--text-muted)" role="alert">{error}</p>}
          {r && <Body r={r} imperial={imperial} onCheckIn={onCheckIn} onOpenSession={onOpenSession && ((id) => { onClose(); onOpenSession(id) })} onDone={close} />}
        </div>
      </div>
    </div>
  )
}

function Body({ r, imperial, onCheckIn, onOpenSession, onDone }: {
  r: Reaction; imperial: boolean; onCheckIn?: (p: CheckInRequest) => void
  onOpenSession?: (id: string) => void; onDone: () => void
}) {
  const b = BADGE[r.verdict]
  const BIcon = b.icon
  const xp = useCountUp(r.xp.total)
  const a = r.activity
  const p = r.planned
  const best = r.bests[0]
  // The verdict badge pops in; "Nailed it" adds a carrot burst from it (once per card).
  const badge = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (r.verdict !== 'nailed') return
    const t = window.setTimeout(() => burst(badge.current, 'xp'), 320)
    return () => window.clearTimeout(t)
  }, [r.verdict])
  return (
    <>
      <div className="celebrate relative flex flex-col items-center gap-2 overflow-hidden rounded-2xl border border-(--border) bg-(--bg-surface) px-4 pb-4 pt-5 text-center">
        {best && (
          <span className="absolute right-[-34px] top-[14px] rotate-45 bg-(--brand) px-10 py-0.5 text-[0.6471rem] font-semibold uppercase tracking-widest text-(--on-fill)"
            aria-hidden="true">PR</span>
        )}
        <span ref={badge} className={cn('rb-pop inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[0.9412rem] font-semibold', b.cls)}
          style={{ animationDelay: '160ms' }}>
          <BIcon className="size-4" strokeWidth={3} /> {b.label}
        </span>
        <p className="max-w-sm text-[0.8824rem] leading-snug text-(--text)">{r.line}</p>
      </div>

      <div className="grid grid-cols-[auto_1fr_1fr] items-baseline gap-x-3 gap-y-1.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5 text-[0.8235rem]">
        <span />
        <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{p ? 'Planned' : ''}</span>
        <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Actual</span>
        <Stat label="Time" planned={p?.minutes ? fmtDuration(p.minutes) : p ? '–' : ''} actual={fmtDuration(a.minutes)} />
        {!!(a.distance_km || p?.meters) && (
          <Stat label="Distance" planned={p?.meters ? (a.sport === 'swim' ? fmtMeters(p.meters, imperial) : fmtDist(p.meters / 1000, imperial)) : p ? '–' : ''}
            actual={a.distance_km ? fmtDist(a.distance_km, imperial, a.sport) : '–'} />
        )}
        {!!(a.avg_hr || r.effort?.basis === 'hr') && (
          <Stat label="Avg HR" planned={r.effort?.basis === 'hr' ? r.effort.target ?? '' : p ? `Z${p.zone}` : ''}
            actual={a.avg_hr ? `${Math.round(a.avg_hr)} bpm` : '–'} good={r.effort?.basis === 'hr' ? r.effort.in_zone : null} />
        )}
        {a.pace && (
          <Stat label="Pace" planned={r.effort?.basis === 'pace' ? r.effort.target ?? '' : p?.targets.find((t) => t.kind === 'pace')?.label ?? ''}
            actual={a.pace} good={r.effort?.basis === 'pace' ? r.effort.in_zone : null} />
        )}
        {!!a.avg_power_w && (
          <Stat label="Power" planned={p?.targets.find((t) => t.kind === 'power')?.label ?? ''} actual={`${Math.round(a.avg_power_w)} W`}
            good={r.effort?.basis === 'power' ? r.effort.in_zone : null} />
        )}
      </div>

      <div className="flex flex-col items-center gap-1 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-3 text-center">
        <div className="flex items-center gap-4">
          <span className={cn('font-display text-[1.6471rem] leading-none text-(--accent)', r.xp.total > 0 && xp === r.xp.total && 'fx-hop')}
            aria-label={`${r.xp.total} XP earned`}>+{xp} XP</span>
          {r.streak.current > 0 && (
            <span className="flex items-center gap-1 text-[0.9412rem] font-semibold text-(--accent)" aria-label={`${r.streak.current} day streak`}>
              <Flame className="size-4" />{r.streak.current}-day streak
            </span>
          )}
        </div>
        {r.xp.plan > 0 && <p className="text-[0.6471rem] text-(--text-muted)">{r.xp.workout} for the workout + {r.xp.plan} for sticking to the plan</p>}
      </div>

      {r.bests.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {r.bests.map((x) => (
            <p key={x.key} className="flex items-center gap-2 rounded-xl border border-(--brand)/30 bg-(--bg-surface) px-3 py-2 text-[0.8235rem] font-medium text-(--brand)">
              <Award className="size-4 shrink-0" />{x.label}
            </p>
          ))}
        </div>
      )}

      {r.gear && (
        <p className={cn('flex items-center gap-2 rounded-xl border px-3 py-2 text-[0.7647rem]',
          r.gear.warning ? 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)' : 'border-(--border) bg-(--bg-surface) text-(--text-secondary)')}>
          <Footprints className="size-4 shrink-0" />
          <span className="min-w-0 flex-1">{r.gear.label}{r.gear.warning ? ` · ${r.gear.warning}` : ` · ${r.gear.total_label} total`}</span>
        </p>
      )}

      {r.tomorrow && (
        <button type="button" disabled={!r.tomorrow.id || !onOpenSession}
          onClick={() => r.tomorrow?.id && onOpenSession?.(r.tomorrow.id)}
          className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5 text-left enabled:active:bg-(--bg-inset)">
          {r.tomorrow.rest ? <Moon className="size-4 shrink-0 text-(--text-muted)" /> : <CalendarClock className="size-4 shrink-0 text-(--accent)" />}
          <span className="min-w-0 flex-1">
            <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
              Tomorrow · {fmtDay(r.tomorrow.date, { weekday: 'long' })}
            </span>
            <span className="block truncate text-[0.8235rem] text-(--text)">
              {r.tomorrow.title}{r.tomorrow.minutes ? ` · ${fmtDuration(r.tomorrow.minutes)}` : ''}{r.tomorrow.more ? ` +${r.tomorrow.more} more` : ''}
            </span>
          </span>
          {r.tomorrow.id && onOpenSession && <ChevronRight className="size-4 shrink-0 text-(--text-muted)" />}
        </button>
      )}

      <div className="flex gap-2">
        {onCheckIn && (
          <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]"
            onClick={() => onCheckIn({ activityId: a.id, sessionId: r.session_id ?? undefined, title: a.name })}>
            How did it feel?
          </Button>
        )}
        <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={onDone}>Done</Button>
      </div>
      {typeof a.id === 'number' && <ShareWorkoutButton activityId={a.id} />}
      {typeof a.id === 'number' && (
        <Button variant="ghost" className="h-11 gap-1 text-[0.7647rem]" onClick={() => { const id = a.id as number; onDone(); window.setTimeout(() => openActivity(id), 220) }}>
          See every detail: laps, zones, heart rate <ChevronRight className="size-4" aria-hidden />
        </Button>
      )}
    </>
  )
}

function Stat({ label, planned, actual, good }: { label: string; planned: string; actual: string; good?: boolean | null }) {
  return (
    <>
      <span className="text-[0.7059rem] text-(--text-muted)">{label}</span>
      <span className="truncate text-(--text-secondary)">{planned}</span>
      <span className={cn('truncate font-semibold', good === false ? 'text-(--warning-text)' : good ? 'text-(--accent)' : 'text-(--text)')}>{actual}</span>
    </>
  )
}
