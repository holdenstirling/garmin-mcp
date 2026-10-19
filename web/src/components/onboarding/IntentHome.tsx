// Rabbit home, tailored: one compact strip for what the athlete came for (their top intent).
// consistent -> streak + challenge progress; community -> "From your community" (latest 1-2
// friend or club highlights; hides when there's nothing); events -> next event countdown +
// "Explore near you"; coach -> coach messages or Find a coach. train/explore -> nothing (the
// Today card and plan banner already lead). Chat decides where it sits; this only draws it.
import { useEffect, useState, type ReactNode } from 'react'
import { CalendarDays, ChevronRight, MapPin, MessageCircle, Trophy, UserRound, Users } from 'lucide-react'
import { HopIn, StreakFlame } from '@/components/anim'
import type { Me } from '@/lib/api'
import { getChallenges, type Joined } from '@/lib/challenges'
import { countdown, daysUntil, listEvents, type RaceEvent } from '@/lib/events'
import { communityHighlights, primaryIntent, type Highlight, type Intent } from '@/lib/intent'
import type { Progress } from '@/lib/progress'
import { cn } from '@/lib/utils'

export type HomeTarget = 'progress' | 'events' | 'explore' | 'friends' | 'coach' | 'findcoach'

/** Intents whose strip goes above the Today card (train keeps Today first). */
export const stripFirst = (intents: readonly Intent[]) => {
  const p = primaryIntent(intents)
  return p === 'consistent' || p === 'community' || p === 'events' || p === 'coach'
}

const chip = 'flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border px-3 text-small font-medium active:opacity-70'
const chipAccent = 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)'
const chipPlain = 'border-(--border) bg-(--bg-surface) text-(--text-secondary)'

function Strip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <HopIn as="section" className="mx-4 mt-2 shrink-0" aria-label={label}>
      <div className="flex gap-2 overflow-x-auto [scrollbar-width:none]">{children}</div>
    </HopIn>
  )
}

export function IntentStrip({ intents, me, progress, onOpen, communitySlot, refreshKey }: {
  intents: readonly Intent[]
  me: Me
  progress: Progress | null
  onOpen: (t: HomeTarget) => void
  /** Community feature: its own highlight row replaces the default friends-feed one */
  communitySlot?: ReactNode
  /** bump to re-read (e.g. after a sync) */
  refreshKey?: unknown
}) {
  const p = primaryIntent(intents)
  if (p === 'consistent') return <ConsistentStrip progress={progress} onOpen={onOpen} refreshKey={refreshKey} />
  if (p === 'community') return communitySlot ? <>{communitySlot}</> : <CommunityStrip onOpen={onOpen} refreshKey={refreshKey} />
  if (p === 'events') return <EventsStrip onOpen={onOpen} refreshKey={refreshKey} />
  if (p === 'coach') return <CoachStrip me={me} onOpen={onOpen} />
  return null
}

function ConsistentStrip({ progress, onOpen, refreshKey }: { progress: Progress | null; onOpen: (t: HomeTarget) => void; refreshKey?: unknown }) {
  const [ch, setCh] = useState<Joined | null | undefined>(undefined)
  useEffect(() => {
    let live = true
    getChallenges().then((v) => { if (live) setCh(v.joined.find((j) => !j.done) ?? v.joined[0] ?? null) }, () => { if (live) setCh(null) })
    return () => { live = false }
  }, [refreshKey])
  const s = progress?.streak
  return (
    <Strip label="Your streak and challenges">
      {s && (
        <button type="button" className={cn(chip, s.at_risk ? 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)' : chipAccent)} onClick={() => onOpen('progress')}>
          <StreakFlame streak={s.current} atRisk={s.at_risk} className="size-4" />
          {s.current > 0 ? `${s.current} day streak${s.at_risk ? ' · keep it alive today' : s.today_done ? ' · done today' : ''}` : 'Start a streak today'}
        </button>
      )}
      {ch !== undefined && (
        <button type="button" className={cn(chip, chipPlain)} onClick={() => onOpen('progress')}>
          <Trophy className="size-5 text-(--accent)" />
          {ch ? `${ch.name} · ${Math.round(ch.pct)}%` : 'Pick a challenge'}
          <ChevronRight className="size-4" />
        </button>
      )}
    </Strip>
  )
}

function CommunityStrip({ onOpen, refreshKey }: { onOpen: (t: HomeTarget) => void; refreshKey?: unknown }) {
  const [items, setItems] = useState<Highlight[]>([])
  useEffect(() => {
    let live = true
    void communityHighlights().then((h) => { if (live) setItems(h) })
    return () => { live = false }
  }, [refreshKey])
  if (!items.length) return null // nothing yet: hide quietly
  return (
    <HopIn as="section" className="mx-4 mt-2 shrink-0 rounded-xl border border-(--border) bg-(--bg-surface)" aria-label="From your community">
      <button type="button" onClick={() => onOpen('friends')} className="flex min-h-11 w-full items-center gap-2 px-3 pt-2 text-left">
        <Users className="size-5 shrink-0 text-(--accent)" />
        <span className="flex-1 text-meta font-semibold text-(--text-muted)">From your community</span>
        <ChevronRight className="size-5 text-(--text-muted)" />
      </button>
      <ul className="px-3 pb-2">
        {items.map((h) => (
          <li key={h.id} className="truncate py-0.5 text-small text-(--text)">
            {h.who && <span className="font-semibold">{h.who}: </span>}{h.title}
            {h.subtitle && <span className="text-(--text-muted)"> · {h.subtitle}</span>}
          </li>
        ))}
      </ul>
    </HopIn>
  )
}

function EventsStrip({ onOpen, refreshKey }: { onOpen: (t: HomeTarget) => void; refreshKey?: unknown }) {
  const [next, setNext] = useState<RaceEvent | null>(null)
  useEffect(() => {
    let live = true
    listEvents().then((r) => {
      const up = r.events.filter((e) => e.date && daysUntil(e.date) >= 0).sort((a, b) => a.date.localeCompare(b.date))
      if (live) setNext(up[0] ?? null)
    }, () => {})
    return () => { live = false }
  }, [refreshKey])
  return (
    <Strip label="Your events">
      {next && (
        <button type="button" className={cn(chip, chipAccent, 'max-w-[70%]')} onClick={() => onOpen('events')}>
          <CalendarDays className="size-5 shrink-0" />
          <span className="truncate">{next.name}</span>
          <span className="shrink-0 font-semibold">· {countdown(next.date)}</span>
        </button>
      )}
      <button type="button" className={cn(chip, next ? chipPlain : chipAccent)} onClick={() => onOpen('explore')}>
        <MapPin className="size-5" /> Explore near you
      </button>
    </Strip>
  )
}

function CoachStrip({ me, onOpen }: { me: Me; onOpen: (t: HomeTarget) => void }) {
  return (
    <Strip label="Your coach">
      {me.coaches > 0 ? (
        <button type="button" className={cn(chip, me.coach_unread > 0 ? chipAccent : chipPlain)} onClick={() => onOpen('coach')}>
          <MessageCircle className="size-5" />
          {me.coach_unread > 0 ? `${me.coach_unread} new from your coach` : 'Message your coach'}
        </button>
      ) : (
        <button type="button" className={cn(chip, chipAccent)} onClick={() => onOpen('findcoach')}>
          <UserRound className="size-5" /> Find a coach <ChevronRight className="size-4" />
        </button>
      )}
    </Strip>
  )
}
