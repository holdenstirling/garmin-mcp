// Small Rabbit home cards: the greeting, the next race countdown (tap: Races) and a progress
// glance (streak, this week, level; tap: Progress).
import { useEffect, useState } from 'react'
import { ChevronRight, Flag, Flame, Sparkles, Target } from 'lucide-react'
import { daysUntil, isRace, listEvents, TYPE_LABEL, type RaceEvent } from '@/lib/events'
import type { Progress } from '@/lib/progress'
import { cn } from '@/lib/utils'

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 5 ? 'Up late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function HomeGreeting({ name }: { name: string | null | undefined }) {
  const now = new Date()
  const first = name?.trim().split(/\s+/)[0]
  return (
    <div className="px-0.5">
      <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
        {now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}
      </p>
      <h2 className="font-display text-[1.4118rem] leading-tight text-(--brand)">{greeting(now)}{first ? `, ${first}` : ''}</h2>
    </div>
  )
}

/** The next race (main first when tied), 8+ days out; race week has its own card. */
export function NextRaceCard({ refreshKey, onOpen }: { refreshKey?: number; onOpen: () => void }) {
  const [ev, setEv] = useState<RaceEvent | null>(null)
  useEffect(() => {
    let live = true
    listEvents().then((r) => {
      const next = r.events.filter((e) => isRace(e) && daysUntil(e.date) >= 0)
        .sort((a, b) => a.date.localeCompare(b.date) || Number(b.main) - Number(a.main))[0] ?? null
      if (live) setEv(next)
    }, () => {})
    return () => { live = false }
  }, [refreshKey])
  if (!ev) return null
  const n = daysUntil(ev.date)
  if (n <= 7 && (ev.main || ev.priority !== 'C')) return null // RaceWeekCard has it
  const when = new Date(`${ev.date}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
  const what = [ev.distance, TYPE_LABEL[ev.type]].filter(Boolean).join(' ')
  return (
    <button type="button" onClick={onOpen} aria-label={`Next race: ${ev.name}, ${when}, in ${n} days. Open Races`}
      className="settings-group flex min-h-16 w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)" aria-hidden>
        <Flag className="size-5" />
      </span>
      <span className="min-w-0 flex-1" aria-hidden>
        <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Next race</span>
        <span className="block truncate text-[0.8824rem] font-semibold text-(--text)">{ev.name}</span>
        <span className="block truncate text-[0.7059rem] text-(--text-muted)">{when}{what ? ` · ${what}` : ''}</span>
      </span>
      <span className="flex shrink-0 flex-col items-end leading-none" aria-hidden>
        <span className="font-display text-[1.6471rem] text-(--brand)">{n}</span>
        <span className="text-[0.6471rem] text-(--text-muted)">{n === 1 ? 'day' : 'days'}</span>
      </span>
    </button>
  )
}

function Stat({ icon: Icon, value, label, hot }: { icon: typeof Flame; value: string; label: string; hot?: boolean }) {
  return (
    <span className="flex min-w-0 flex-1 flex-col items-center gap-0.5 px-1 py-2.5">
      <Icon className={cn('size-4', hot ? 'text-(--accent)' : 'text-(--text-muted)')} aria-hidden />
      <span className="font-mono text-[0.9412rem] font-semibold text-(--text)">{value}</span>
      <span className="truncate text-[0.6471rem] text-(--text-muted)">{label}</span>
    </span>
  )
}

export function ProgressGlance({ progress, onOpen }: { progress: Progress | null; onOpen: () => void }) {
  if (!progress) return <div className="skeleton h-[74px] rounded-xl" aria-hidden />
  const { streak, week } = progress
  const label = `Progress: ${streak.current} day streak, this week ${week.done} of ${week.target}, level ${progress.level} ${progress.name}. Open Progress`
  return (
    <button type="button" onClick={onOpen} aria-label={label}
      className="settings-group flex w-full items-center rounded-xl border border-(--border) bg-(--bg-surface) px-1 text-left active:bg-(--bg-inset)">
      <Stat icon={Flame} value={String(streak.current)} label="day streak" hot={streak.today_done} />
      <span className="h-8 w-px bg-(--border)" aria-hidden />
      <Stat icon={Target} value={`${week.done}/${week.target}`} label={week.label || 'this week'} hot={week.target > 0 && week.done >= week.target} />
      <span className="h-8 w-px bg-(--border)" aria-hidden />
      <Stat icon={Sparkles} value={`Lv ${progress.level}`} label={progress.name} />
      <ChevronRight className="mr-2 size-4 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}
