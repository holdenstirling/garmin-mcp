// One day of the plan, everything about it: each session's full description, length and status,
// the Garmin workout you did (tap: its full page), Ask Rabbit, and, for a plan that comes from a
// file (no session ids), "Get full workouts" to turn the whole plan into Rabbit workouts.
import { BookOpen, Check, ChevronRight, MessageCircle } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { SPORT_ICON, fmtDay } from '@/components/plan/PlanParts'
import { fmtMinutes } from '@/components/chat/PlanPins'
import { fmtDist } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DoneActivity, PlannedSession, WeekDay } from '@/lib/api'
import { openActivity } from '@/lib/activitynav'
import { openWorkout } from '@/lib/workoutnav'
import { startPlanConversion } from '@/lib/planconvert'

const STATUS: Record<string, { label: string; cls: string }> = {
  done: { label: 'Done', cls: 'bg-(--accent-subtle) text-(--accent)' },
  missed: { label: 'Missed', cls: 'bg-(--danger)/10 text-(--danger)' },
  planned: { label: 'Planned', cls: 'bg-(--bg-inset) text-(--text-secondary)' },
}

function ActivityRow({ a, imperial }: { a: DoneActivity; imperial: boolean }) {
  const Icon = SPORT_ICON[a.sport] ?? Check
  const body = (
    <>
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)"><Icon className="size-4" aria-hidden /></span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[0.8235rem] font-medium text-(--text)">{a.name}</span>
        <span className="block text-[0.7059rem] text-(--text-muted)">
          {[a.distance_km ? fmtDist(a.distance_km, imperial, a.sport) : '', a.minutes ? fmtMinutes(a.minutes) : ''].filter(Boolean).join(' · ')}
          {a.id != null && ' · see every detail'}
        </span>
      </span>
      {a.id != null && <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />}
    </>
  )
  return a.id != null ? (
    <button type="button" onClick={() => openActivity(a.id!)} aria-label={`${a.name}: open the workout you did`}
      className="flex min-h-12 w-full items-center gap-3 rounded-lg border border-(--border) bg-(--bg-surface) px-3 py-2 text-left active:bg-(--bg-inset)">{body}</button>
  ) : <div className="flex min-h-12 items-center gap-3 rounded-lg border border-(--border) px-3 py-2">{body}</div>
}

export function PlanDaySheet({ day, imperial, onClose, onAsk }: {
  day: WeekDay; imperial: boolean; onClose: () => void
  onAsk: (day: WeekDay, session?: PlannedSession) => void
}) {
  const work = day.sessions.filter((s) => s.status !== 'rest')
  const fromFile = work.some((s) => !s.id)
  return (
    <Sheet title={fmtDay(day.date, { weekday: 'long', month: 'long', day: 'numeric' })} onClose={onClose} portal
      bodyClassName="settings flex flex-col gap-3 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      {!work.length && !day.extra.length && <p className="text-[0.8235rem] text-(--text-secondary)">Rest day. Nothing planned.</p>}
      {work.map((s, i) => {
        const Icon = SPORT_ICON[s.sport] ?? Check
        const st = STATUS[s.status] ?? STATUS.planned!
        return (
          <section key={i} aria-label={s.title} className="flex flex-col gap-3 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
            <div className="flex items-start gap-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)"><Icon className="size-5" aria-hidden /></span>
              <span className="min-w-0 flex-1">
                <span className="block text-[0.9412rem] font-semibold leading-snug text-(--text)">{s.title}</span>
                {s.minutes ? <span className="block text-[0.7647rem] text-(--text-muted)">{fmtMinutes(s.minutes)}</span> : null}
              </span>
              <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[0.6471rem] font-semibold', st.cls)}>{st.label}</span>
            </div>
            {s.detail && <p className="m-0 whitespace-pre-line text-[0.8235rem] leading-relaxed text-(--text-secondary)">{s.detail}</p>}
            {s.activity && <ActivityRow a={s.activity} imperial={imperial} />}
            <div className="flex flex-wrap gap-2">
              {s.id && (
                <Button variant="primary" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={() => { onClose(); openWorkout(s.id!, day.date) }}>
                  Open full workout
                </Button>
              )}
              <Button variant="default" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={() => { onClose(); onAsk(day, s) }}>
                <MessageCircle className="size-4" aria-hidden /> Ask rabbt
              </Button>
            </div>
          </section>
        )
      })}
      {day.extra.length > 0 && (
        <section aria-label="Also from Garmin" className="flex flex-col gap-2">
          <p className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Also from Garmin</p>
          {day.extra.map((a, i) => <ActivityRow key={a.id ?? i} a={a} imperial={imperial} />)}
        </section>
      )}
      {fromFile && (
        <section className="flex flex-col gap-2 rounded-xl border border-(--accent)/40 bg-(--accent-subtle) p-4">
          <p className="m-0 flex items-center gap-1.5 text-[0.8235rem] font-semibold text-(--accent)"><BookOpen className="size-4" aria-hidden /> Want the full workout?</p>
          <p className="m-0 text-[0.7647rem] leading-snug text-(--text-secondary)">
            This day comes from your plan file, so rabbt only has its description. Turn the plan into full workouts to get heart-rate zones, pace, cadence and steps for every day, plus moving days and sending to your watch.
          </p>
          <Button variant="primary" className="h-11 text-[0.8235rem]" onClick={() => { onClose(); startPlanConversion() }}>
            Get full workouts (zones, pace, cadence)
          </Button>
        </section>
      )}
    </Sheet>
  )
}
