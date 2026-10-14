// "Today" on home: one deterministic recommendation (server: today.py). One headline, one
// line of detail, up to 3 signal chips, one primary action and an "Ask Rabbit" link.
// Collapses to a single line; the collapsed state is remembered for the day.
import { useState } from 'react'
import { Check, ChevronDown, Flag, Moon, Sparkles, Waves, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { InfoTip } from '@/components/ui/InfoTip'
import type { Term } from '@/lib/glossary'
import { cn } from '@/lib/utils'
import type { Today, TodayActionKind, TodayTone } from '@/lib/live'

const KEY = 'rabbit.today.collapsed'

/** Signal chip labels that get a plain-language (i). */
const SIGNAL_TERM: Record<string, Term> = {
  Form: 'form', Readiness: 'readiness', 'Oura readiness': 'oura_readiness', 'Garmin readiness': 'garmin_readiness', Streak: 'streak',
}

const TONE: Record<TodayTone, { icon: typeof Zap; color: string; border: string; bg: string }> = {
  go: { icon: Zap, color: 'text-(--accent)', border: 'border-(--accent)/30', bg: 'bg-(--accent)' },
  done: { icon: Check, color: 'text-(--accent)', border: 'border-(--accent)/30', bg: 'bg-(--accent)' },
  plan: { icon: Sparkles, color: 'text-(--accent)', border: 'border-(--accent)/30', bg: 'bg-(--accent)' },
  easy: { icon: Waves, color: 'text-(--accent)', border: 'border-(--accent)/30', bg: 'bg-(--accent)' },
  rest: { icon: Moon, color: 'text-(--text-secondary)', border: 'border-(--border-strong)', bg: 'bg-(--text-muted)' },
  race: { icon: Flag, color: 'text-(--brand)', border: 'border-(--brand)/30', bg: 'bg-(--brand)' },
}

function readCollapsed(day: string): boolean {
  try { return window.localStorage.getItem(KEY) === day } catch { return false }
}

function writeCollapsed(day: string, on: boolean) {
  try {
    if (on) window.localStorage.setItem(KEY, day)
    else window.localStorage.removeItem(KEY)
  } catch { /* storage unavailable: just this session */ }
}

export function TodayCard({ today, onAction, onAsk, onOpenWorkout }: {
  today: Today; onAction: (kind: TodayActionKind) => void; onAsk: (text: string) => void
  /** today's planned session: the primary action opens the pre-workout screen */
  onOpenWorkout?: (sessionId: string) => void
}) {
  const [collapsedDay, setCollapsedDay] = useState<string | null>(() => (readCollapsed(today.date) ? today.date : null))
  const collapsed = collapsedDay === today.date
  const t = TONE[today.tone] ?? TONE.go
  const Icon = t.icon
  const workoutId = today.action.kind === 'open_session' ? today.session?.id ?? null : null
  const toggle = () => {
    const next = !collapsed
    writeCollapsed(today.date, next)
    setCollapsedDay(next ? today.date : null)
  }
  return (
    <section aria-label="Today" className={cn('coach-pins mx-4 mt-3 shrink-0 rounded-xl border bg-(--bg-surface)', t.border)}>
      <button type="button" onClick={toggle} aria-expanded={!collapsed}
        className="flex w-full items-center gap-2.5 px-3 pt-2.5 text-left" style={{ paddingBottom: collapsed ? 10 : 0 }}>
        <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-full text-white', t.bg)}>
          <Icon className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Today</span>
          <span className={cn('block truncate text-[0.8235rem] font-semibold leading-tight', t.color)}>{today.headline}</span>
        </span>
        <ChevronDown className={cn('size-4 shrink-0 text-(--text-muted) transition-transform', !collapsed && 'rotate-180')} />
      </button>
      {!collapsed && (
        <div className="flex flex-col gap-2 px-3 pb-2.5 pt-1.5">
          <p className="text-[0.7647rem] leading-snug text-(--text)">{today.detail}</p>
          {today.signals.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {today.signals.map((s) => (
                <span key={s.label}
                  className={cn('inline-flex items-center gap-1 rounded-full border py-0.5 pl-2 text-[0.7059rem] font-medium',
                    SIGNAL_TERM[s.label] ? 'pr-1' : 'pr-2',
                    s.good ? 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)'
                      : 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)')}>
                  {s.label} {s.value}
                  {SIGNAL_TERM[s.label] && <InfoTip term={SIGNAL_TERM[s.label]} />}
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center gap-3">
            <Button variant="primary" className="hit-44 h-8 px-3 text-[0.7059rem]" onClick={() => (workoutId && onOpenWorkout ? onOpenWorkout(workoutId) : onAction(today.action.kind))}>
              {today.action.label}
            </Button>
            <button type="button" className="hit-44 text-[0.7059rem] text-(--text-muted) underline-offset-2 hover:underline"
              onClick={() => onAsk(`About today's recommendation (${today.headline}): `)}>
              Ask Rabbit
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
