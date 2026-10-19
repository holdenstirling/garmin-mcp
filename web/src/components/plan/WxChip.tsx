// Day view: a small weather chip on an upcoming session (today + 2 days) when the forecast
// changes it (heat, wind, storms, ice, cold, altitude, air). Data: lib/weather getNextDays
// (cached; shared with Home's "Next 3 days"). Tap the workout for the full weather section.
import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { BADGE, getNextDays, type NextDays } from '@/lib/weather'

let shared: NextDays | null = null

export function WxChip({ id, date }: { id: string; date: string }) {
  const [d, setD] = useState<NextDays | null>(shared)
  useEffect(() => {
    let live = true
    getNextDays().then((r) => { shared = r; if (live) setD(r) }, () => {})
    return () => { live = false }
  }, [])
  const s = d?.days.find((x) => x.date === date)?.sessions.find((x) => x.id === id)
  const b = s?.badges.find((x) => x !== 'rain') ?? s?.badges[0]
  if (!s || !b) return null
  const B = BADGE[b]
  return (
    <span className={cn('flex shrink-0 items-center gap-0.5 rounded-full px-2 py-0.5 text-caption font-semibold',
      B.warn ? 'bg-(--warning-subtle) text-(--warning-text)' : 'bg-(--bg-inset) text-(--text-secondary)')}
      aria-label={`Weather: ${s.badges.map((x) => BADGE[x].label).join(', ')}${s.pct ? `, paces about ${s.pct}% slower` : ''}`}>
      <B.icon className="size-3" aria-hidden />{b === 'heat' && s.pct ? `+${Math.round(s.pct)}%` : B.label}
    </span>
  )
}
