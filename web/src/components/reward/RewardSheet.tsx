// Post-workout reward (server: reward.py): one headline from the athlete's own data, 2-3 stat
// chips, the XP bar filling from before to after this workout, a one-tap "How did it feel?"
// and "Share with friends". Shown once per workout (marked seen as it opens); from the
// workout push too. Motion is transform/opacity/width only and still under reduced motion.
import { useEffect, useRef, useState } from 'react'
import { Award, Check, ChevronRight, Flame, X } from 'lucide-react'
import { useSheetDrag } from '@/hooks/useSheetDrag'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { RabbitLogo } from '@/components/RabbitLogo'
import { ShareWorkoutButton } from '@/components/community/ShareWorkout'
import { burst, reducedMotion, useCountUp } from '@/components/anim'
import { createCheckin } from '@/lib/checkins'
import { getReward, markRewardSeen, type LevelView, type Reward } from '@/lib/reward'
import { cn } from '@/lib/utils'
import { CelebrationScreen } from './CelebrationScreen'

const FACES: [number, string, string][] = [[1, '😫', 'Awful'], [2, '🙁', 'Rough'], [3, '😐', 'OK'], [4, '🙂', 'Good'], [5, '😄', 'Great']]
const RECORD = new Set(['split_5k', 'split_10k', 'distance', 'climb', 'duration', 'effect'])
/** Best in 12 months or ever (celebrate.big_record): a full-screen moment before the sheet. */
const BIG = new Set(['split_5k', 'split_10k', 'distance'])
const bigRecord = (r: Reward) => BIG.has(r.headline.kind) && r.headline.weeks == null && !r.seen

export function RewardSheet({ activityId, initial, onClose, onBreakdown, onCheckIn, onFeel }: {
  /** which workout; the sheet loads it unless ``initial`` already has it */
  activityId: number
  initial?: Reward | null
  onClose: () => void
  /** "See breakdown": the post-workout reaction card */
  onBreakdown?: (activityId: number) => void
  /** "Add details": the voice check-in */
  onCheckIn?: (p: { activityId: number; sessionId?: string; title: string }) => void
  /** after a one-tap feel was saved (XP may have changed) */
  onFeel?: (xp: number) => void
}) {
  const [r, setR] = useState<Reward | null>(initial && initial.activity_id === activityId ? initial : null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const drag = useSheetDrag(onClose)
  const [party, setParty] = useState<boolean | null>(null) // null until the reward is here
  useEffect(() => { if (r && party === null) setParty(bigRecord(r)) }, [r, party])
  useEffect(() => {
    let live = true
    if (!r) {
      getReward(activityId).then((x) => {
        if (!live) return
        if (x.reward) setR(x.reward); else setError("This workout's reward isn't here any more.")
      }, (e: Error) => { if (live) setError(e.message) })
    }
    markRewardSeen(activityId).catch(() => { /* shown again next time; harmless */ })
    return () => { live = false }
  }, [activityId]) // eslint-disable-line react-hooks/exhaustive-deps
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }

  if (r && party) {
    return (
      <CelebrationScreen c={{
        id: `pr:${r.activity_id}`, kind: 'pr', date: r.date, title: 'New personal record', subtitle: r.headline.text,
        line: r.headline.text.includes('12 months') ? 'Your best in a year. The work is showing.' : 'Your best ever on rabbt. Take a moment.',
        stats: r.chips,
      }} onClose={() => setParty(false)} />
    )
  }
  return (
    <div className={`modal-overlay ${closing ? 'modal-overlay--exit' : ''}`} onClick={close}>
      <div className={`modal ${closing ? 'modal--exit' : ''}`} onClick={(e) => e.stopPropagation()} {...drag}
        role="dialog" aria-modal aria-labelledby="reward-title" data-usage-card="reward">
        <div className="sheet-handle" />
        <div className="modal-header">
          <h2 id="reward-title" className="modal-title">Nice work</h2>
          <button className="modal-close hit-44" aria-label="Close" onClick={close}><X className="size-4" /></button>
        </div>
        <div className="modal-body flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          {!r && !error && <RabbitLoader className="py-10" label="Loading your reward" cycle={['Checking your records…', 'Counting your XP…']} />}
          {error && <p className="py-8 text-center text-[0.8235rem] text-(--text-muted)" role="alert">{error}</p>}
          {r && <Body r={r} onDone={close} onFeel={onFeel}
            onBreakdown={onBreakdown && (() => { onClose(); onBreakdown(r.activity_id) })}
            onCheckIn={onCheckIn && (() => { onClose(); onCheckIn({ activityId: r.activity_id, sessionId: r.session_id ?? undefined, title: r.name }) })} />}
        </div>
      </div>
    </div>
  )
}

function Body({ r, onDone, onBreakdown, onCheckIn, onFeel }: {
  r: Reward; onDone: () => void; onBreakdown?: () => void; onCheckIn?: () => void; onFeel?: (xp: number) => void
}) {
  const xp = useCountUp(r.xp.gained, { duration: 900 })
  const record = RECORD.has(r.headline.kind)
  const hero = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const t = window.setTimeout(() => burst(hero.current, record ? 'badge' : 'xp'), 260)
    return () => window.clearTimeout(t)
  }, [record])
  const day = new Date(`${r.date}T12:00:00`)
  return (
    <>
      <div ref={hero} className="celebrate flex flex-col items-center gap-2 rounded-2xl bg-(--brand) px-4 pb-5 pt-5 text-center text-(--on-fill)">
        <span className="flex items-center gap-1.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest opacity-90">
          {record ? <Award className="size-3.5" aria-hidden="true" /> : <RabbitLogo size={14} current />}
          {record ? 'New best' : 'Workout done'}
        </span>
        <p className="rb-pop m-0 max-w-sm font-display text-[1.6471rem] leading-tight" style={{ animationDelay: '120ms' }}>{r.headline.text}</p>
        <p className="m-0 text-[0.7647rem] opacity-90">
          {r.name} · {Number.isNaN(day.getTime()) ? '' : day.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}
        </p>
      </div>

      {r.chips.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0" style={{ gridTemplateColumns: `repeat(${r.chips.length}, minmax(0, 1fr))` }}>
          {r.chips.map((c) => (
            <li key={c.label} className="flex flex-col items-center rounded-xl border border-(--border) bg-(--bg-surface) px-2 py-2">
              <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{c.label}</span>
              <span className="font-mono text-[0.9412rem] font-medium tabular-nums text-(--text)">{c.value}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-3">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-display text-[1.5294rem] leading-none text-(--accent)" aria-label={`${r.xp.gained} XP earned`}>+{xp} XP</span>
          {r.streak > 0 && (
            <span className="flex items-center gap-1 text-[0.8235rem] font-semibold text-(--accent)">
              <Flame className="size-4" aria-hidden="true" />{r.streak}-day streak
            </span>
          )}
        </div>
        <LevelBar before={r.level.before} after={r.level.after} levelUp={r.level.level_up} />
        {r.xp.plan > 0 && <p className="m-0 text-[0.7059rem] text-(--text-muted)">{r.xp.workout} for the workout + {r.xp.plan} for sticking to the plan</p>}
      </div>

      <Feel r={r} onCheckIn={onCheckIn} onFeel={onFeel} />

      <ShareWorkoutButton activityId={r.activity_id} />
      <div className="flex gap-2">
        {onBreakdown && (
          <Button variant="default" className="h-11 flex-1 gap-1 text-[0.8235rem]" onClick={onBreakdown}>
            See breakdown <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        )}
        <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" onClick={onDone}>Done</Button>
      </div>
    </>
  )
}

/** XP bar from before this workout to after it; a level-up fills, then starts the new level. */
function LevelBar({ before, after, levelUp }: { before: LevelView; after: LevelView; levelUp: boolean }) {
  const pct = (v: LevelView) => Math.max(2, Math.min(100, Math.round((100 * v.level_xp) / Math.max(1, v.level_span))))
  const still = reducedMotion()
  const [stage, setStage] = useState<'start' | 'full' | 'end'>(still ? 'end' : 'start')
  useEffect(() => {
    if (still) return
    const timers = levelUp
      ? [window.setTimeout(() => setStage('full'), 80), window.setTimeout(() => setStage('end'), 900)]
      : [window.setTimeout(() => setStage('end'), 80)]
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [levelUp, still])
  const width = stage === 'start' ? pct(before) : stage === 'full' ? 100 : pct(after)
  const snap = stage === 'end' && levelUp // new level starts from the left without sliding back
  const shown = stage === 'end' ? after : before
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between text-[0.7647rem]">
        <span className={cn('font-semibold text-(--text)', stage === 'end' && levelUp && 'rb-pop')}>
          {stage === 'end' && levelUp ? `Level up! ${after.level} · ${after.name}` : `Level ${shown.level} · ${shown.name}`}
        </span>
        <span className="font-mono text-[0.7059rem] tabular-nums text-(--text-muted)">{after.to_next} XP to {after.level + 1}</span>
      </div>
      <span className="block h-2 w-full overflow-hidden rounded-full bg-(--bg-elevated)" role="progressbar"
        aria-valuemin={0} aria-valuemax={after.level_span} aria-valuenow={after.level_xp} aria-label="XP to next level">
        <span className={cn('block h-full origin-left rounded-full bg-(--accent)', !snap && 'transition-[width] duration-700 ease-out motion-reduce:transition-none')}
          style={{ width: `${width}%` }} />
      </span>
    </div>
  )
}

/** One tap saves a check-in with just the feel (no AI); "Add details" opens the voice check-in. */
function Feel({ r, onCheckIn, onFeel }: { r: Reward; onCheckIn?: () => void; onFeel?: (xp: number) => void }) {
  const [picked, setPicked] = useState<number | null>(null)
  const [state, setState] = useState<'idle' | 'busy' | 'done'>('idle')
  const [msg, setMsg] = useState<string | null>(null)
  async function pick(v: number, el: HTMLElement) {
    if (state === 'busy') return
    setPicked(v); setState('busy'); setMsg(null)
    try {
      const res = await createCheckin({ text: '', feel: v, activity_id: r.activity_id, ...(r.session_id ? { session_id: r.session_id } : {}) })
      setState('done'); setMsg(res.xp ? `Saved · +${res.xp} XP` : 'Saved')
      if (res.xp) burst(el, 'checkin')
      onFeel?.(res.xp)
    } catch (e) { setState('idle'); setPicked(null); setMsg((e as Error).message) }
  }
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[0.8235rem] font-semibold text-(--text)">How did it feel?</span>
        {state === 'done' && <span className="flex items-center gap-1 text-[0.7059rem] text-(--accent)" role="status"><Check className="size-3.5" aria-hidden="true" />{msg}</span>}
      </div>
      <div className="flex justify-between gap-1" role="group" aria-label="How did it feel?">
        {FACES.map(([v, face, label]) => (
          <button key={v} type="button" disabled={state === 'done' && picked !== v} aria-pressed={picked === v}
            aria-label={`${label} (${v} of 5)`} onClick={(e) => void pick(v, e.currentTarget)}
            className={cn('flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 rounded-xl border py-1.5 transition-colors disabled:opacity-40',
              picked === v ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg)')}>
            <span className="text-[1.2941rem] leading-none" aria-hidden="true">{face}</span>
            <span className="text-[0.6471rem] text-(--text-muted)">{label}</span>
          </button>
        ))}
      </div>
      {state !== 'done' && msg && <p className="m-0 text-[0.7059rem] text-(--danger)" role="alert">{msg}</p>}
      {onCheckIn && (
        <button type="button" onClick={onCheckIn} className="hit-44 self-start text-[0.7059rem] font-medium text-(--accent)">
          {state === 'done' ? 'Add how your legs felt' : 'Say more (sore spots, sleep…)'}
        </button>
      )}
    </div>
  )
}
