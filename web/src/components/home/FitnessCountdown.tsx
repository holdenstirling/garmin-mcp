// Home "Fitness and race countdown": the goal race (or next graded race), days to go, its race
// grade (readiness.py) and whether fitness is rising: fitness (CTL) now against 4 weeks ago from
// the load series. Race week has its own card (RaceWeekCard), so this hides inside 7 days.
// Tap: the race's readiness / race fit page.
import { useEffect, useState } from 'react'
import { ArrowDownRight, ArrowRight, ArrowUpRight, ChevronRight, Flag } from 'lucide-react'
import { listReadiness, mainRace, STATUS_LABEL, type RaceGrade } from '@/lib/readiness'
import { daysUntil } from '@/lib/events'
import { homeLoad } from '@/lib/homedata'
import { cn } from '@/lib/utils'

type Trend = { now: number; delta: number }

export function FitnessCountdown({ refreshKey, onOpen }: { refreshKey: number; onOpen: (eventId: string) => void }) {
  const [race, setRace] = useState<RaceGrade | null | undefined>(undefined)
  const [trend, setTrend] = useState<Trend | null>(null)
  useEffect(() => {
    let live = true
    listReadiness().then((r) => { if (live) setRace(mainRace(r.races.filter((x) => daysUntil(x.date) >= 0))) }, () => { if (live) setRace(null) })
    homeLoad(refreshKey).then((l) => {
      if (!live) return
      const done = l.series.filter((p) => !p.planned && p.date <= l.today)
      const now = done[done.length - 1]
      const back = done[done.length - 29]
      setTrend(now && back ? { now: Math.round(now.ctl), delta: Math.round(now.ctl - back.ctl) } : null)
    }, () => {})
    return () => { live = false }
  }, [refreshKey])

  if (race === undefined) return <div className="skeleton h-[76px] rounded-xl" aria-label="Loading your race" />
  if (!race) return null
  const days = daysUntil(race.date)
  if (days <= 7 && race.main) return null
  const Arrow = !trend ? null : trend.delta >= 2 ? ArrowUpRight : trend.delta <= -2 ? ArrowDownRight : ArrowRight
  const trendWord = !trend ? '' : trend.delta >= 2 ? `Fitness +${trend.delta} in 4 wks` : trend.delta <= -2 ? `Fitness ${trend.delta} in 4 wks` : 'Fitness steady'
  const spoken = !trend ? '' : trend.delta >= 2 ? `Fitness up ${trend.delta} over 4 weeks` : trend.delta <= -2 ? `Fitness down ${-trend.delta} over 4 weeks` : 'Fitness steady over 4 weeks'
  const label = `${race.name}: ${days} days to go. Race grade ${race.grade}, ${STATUS_LABEL[race.status]}. ${spoken}. Open race readiness`
  return (
    <button type="button" onClick={() => onOpen(race.event_id)} aria-label={label}
      className="flex min-h-[76px] w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)">
      <span className="flex size-12 shrink-0 flex-col items-center justify-center rounded-xl bg-(--accent-subtle) leading-none text-(--accent)" aria-hidden>
        <span className="font-display text-[1.2941rem]">{race.grade}</span>
        <span className="mt-0.5 text-[0.6471rem] font-semibold uppercase">grade</span>
      </span>
      <span className="min-w-0 flex-1" aria-hidden>
        <span className="flex items-center gap-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
          <Flag className="size-3" /> {race.main ? 'Goal race' : 'Next race'}
        </span>
        <span className="block truncate text-[0.8824rem] font-semibold text-(--text)">{race.name}</span>
        <span className="flex items-center gap-1 truncate text-[0.7059rem] text-(--text-secondary)">
          <span className={cn(race.status === 'at_risk' || race.status === 'behind' ? 'text-(--warning-text)' : 'text-(--accent)')}>{STATUS_LABEL[race.status]}</span>
          {Arrow && <>· <Arrow className="size-3.5 shrink-0" /> {trendWord}</>}
        </span>
      </span>
      <span className="flex shrink-0 flex-col items-end leading-none" aria-hidden>
        <span className="font-display text-[1.6471rem] text-(--brand)">{days}</span>
        <span className="text-[0.6471rem] text-(--text-muted)">{days === 1 ? 'day' : 'days'}</span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}
