// "Today" on home: one deterministic recommendation (server: today.py). One headline, one
// line of detail, up to 3 signal chips, one primary action and an "Ask Rabbit" link.
// Open the first time you see it each day, then collapsed to one line with the week's dots.
import { useEffect, useState } from 'react'
import { Check, ChevronDown, Flag, Moon, Sparkles, Waves, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Today, TodayActionKind, TodayTone } from '@/lib/live'
import type { WeekDay } from '@/lib/api'
import { WeekDots } from '@/components/week/WeekStrip'

const KEY = 'rabbit.today.seen'

const TONE: Record<TodayTone, { icon: typeof Zap; color: string; border: string; bg: string }> = {
  go: { icon: Zap, color: 'text-(--accent)', border: 'border-(--accent)/30', bg: 'bg-(--accent)' },
  done: { icon: Check, color: 'text-(--accent)', border: 'border-(--accent)/30', bg: 'bg-(--accent)' },
  plan: { icon: Sparkles, color: 'text-(--accent)', border: 'border-(--accent)/30', bg: 'bg-(--accent)' },
  easy: { icon: Waves, color: 'text-(--warning)', border: 'border-(--warning)/30', bg: 'bg-(--warning)' },
  rest: { icon: Moon, color: 'text-(--warning)', border: 'border-(--warning)/30', bg: 'bg-(--warning)' },
  race: { icon: Flag, color: 'text-(--brand)', border: 'border-(--brand)/30', bg: 'bg-(--brand)' },
}

// The day the card was last shown open: later views that day start collapsed.
function seenToday(day: string): boolean {
  try { return window.localStorage.getItem(KEY) === day } catch { return false }
}

export function TodayCard({ today, week, onAction, onAsk, onOpenWorkout }: {
  today: Today; onAction: (kind: TodayActionKind) => void; onAsk: (text: string) => void
  /** this plan week's days: dots in the collapsed row */
  week?: WeekDay[] | null
  /** today's planned session: the primary action opens the pre-workout screen */
  onOpenWorkout?: (sessionId: string) => void
}) {
  const [collapsed, setCollapsed] = useState(() => seenToday(today.date))
  const t = TONE[today.tone] ?? TONE.go
  const Icon = t.icon
  const workoutId = today.action.kind === 'open_session' ? today.session?.id ?? null : null
  useEffect(() => {
    try { window.localStorage.setItem(KEY, today.date) } catch { /* storage unavailable: open each time */ }
  }, [today.date])
  const toggle = () => setCollapsed((c) => !c)
  return (
    <section aria-label="Today" className={cn('coach-pins mx-4 mt-3 shrink-0 rounded-xl border bg-(--bg-surface)', t.border)}>
      <button type="button" onClick={toggle} aria-expanded={!collapsed}
        className="flex w-full items-center gap-2.5 px-3 pt-2.5 text-left" style={{ paddingBottom: collapsed ? 10 : 0 }}>
        <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-full text-white', t.bg)}>
          <Icon className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-[0.5294rem] font-semibold uppercase tracking-widest text-(--text-muted)">Today</span>
          <span className={cn('block truncate text-[0.8235rem] font-semibold leading-tight', t.color)}>{today.headline}</span>
        </span>
        {collapsed && week && week.length === 7 && <WeekDots days={week} />}
        <ChevronDown className={cn('size-4 shrink-0 text-(--text-muted) transition-transform', !collapsed && 'rotate-180')} />
      </button>
      {!collapsed && (
        <div className="flex flex-col gap-2 px-3 pb-2.5 pt-1.5">
          <p className="text-[0.7647rem] leading-snug text-(--text)">{today.detail}</p>
          {today.signals.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {today.signals.map((s) => (
                <span key={s.label}
                  className={cn('rounded-full border px-2 py-0.5 text-[0.5882rem] font-medium',
                    s.good ? 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)'
                      : 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning)')}>
                  {s.label} {s.value}
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center gap-3">
            <Button variant="primary" className="h-8 px-3 text-[0.7059rem]" onClick={() => (workoutId && onOpenWorkout ? onOpenWorkout(workoutId) : onAction(today.action.kind))}>
              {today.action.label}
            </Button>
            <button type="button" className="text-[0.6471rem] text-(--text-muted) underline-offset-2 hover:underline"
              onClick={() => onAsk(`About today's recommendation (${today.headline}): `)}>
              Ask Rabbit
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
