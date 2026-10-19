// A shared workout or event inside a message (snapshot from the sender: no heart rate or location).
// Your own workout links to its full page; a friend's shows what they shared, read-only.
import { Activity, CalendarDays, ChevronRight, MapPin } from 'lucide-react'
import { SPORT_ICON } from '@/components/plan/PlanParts'
import { fmtDay } from '@/components/plan/PlanParts'
import { fmtDist, fmtDuration, fmtPaceKm } from '@/lib/format'
import { openActivity } from '@/lib/activitynav'
import { openWorkout } from '@/lib/workoutnav'
import { openEvent } from '@/lib/events'
import type { DMEventCard, DMWorkoutCard } from '@/lib/dm'
import { cn } from '@/lib/utils'

export function WorkoutCardView({ card, imperial, onOpen }: { card: DMWorkoutCard; imperial: boolean; onOpen?: () => void }) {
  const Icon = (card.sport && (SPORT_ICON as Record<string, typeof Activity>)[card.sport]) || Activity
  const stats = [
    card.km != null ? fmtDist(card.km, imperial, card.sport === 'swim' ? 'swim' : card.sport) : '',
    card.minutes != null ? fmtDuration(card.minutes) : '',
    card.pace != null && card.sport === 'run' ? fmtPaceKm(card.pace, imperial) : '',
  ].filter(Boolean)
  const open = card.mine && card.ref
    ? () => (card.ref!.kind === 'activity' ? openActivity(card.ref!.id) : openWorkout(card.ref!.id, card.ref!.date ?? card.date))
    : onOpen
  const body = (
    <>
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)" aria-hidden>
        <Icon className="size-6" />
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-body font-semibold text-(--text)">{card.title}</span>
        <span className="block truncate text-meta text-(--text-muted)">
          {card.planned ? 'Planned · ' : ''}{card.date ? fmtDay(card.date, { weekday: 'short', month: 'short', day: 'numeric' }) : ''}
        </span>
        {stats.length > 0 && <span className="mt-0.5 block font-mono text-small tabular-nums text-(--text)">{stats.join(' · ')}</span>}
      </span>
      {open && <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />}
    </>
  )
  const cls = 'flex w-full min-w-[220px] items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5'
  return open
    ? <button type="button" className={cn(cls, 'active:bg-(--bg-inset)')} onClick={open}
        aria-label={`${card.title}${stats.length ? `, ${stats.join(', ')}` : ''}. ${card.mine ? 'Open your workout' : 'See details'}`}>{body}</button>
    : <div className={cls}>{body}</div>
}

export function EventCardView({ card }: { card: DMEventCard }) {
  const open = card.mine && card.ref ? () => openEvent(card.ref!.id) : undefined
  const body = (
    <>
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--accent-subtle) text-(--accent)" aria-hidden>
        <CalendarDays className="size-6" />
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-body font-semibold text-(--text)">{card.name}</span>
        <span className="block truncate text-meta text-(--text-muted)">
          {card.repeat_text || (card.date ? fmtDay(card.date, { weekday: 'short', month: 'short', day: 'numeric' }) : '')}{card.time ? ` · ${card.time}` : ''}
        </span>
        {card.neighborhood && (
          <span className="mt-0.5 flex items-center gap-1 text-meta text-(--text-secondary)"><MapPin className="size-3.5" aria-hidden />{card.neighborhood}</span>
        )}
      </span>
      {open && <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />}
    </>
  )
  const cls = 'flex w-full min-w-[220px] items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5'
  return open
    ? <button type="button" className={cn(cls, 'active:bg-(--bg-inset)')} onClick={open} aria-label={`${card.name}. Open the event`}>{body}</button>
    : <div className={cls}>{body}</div>
}
