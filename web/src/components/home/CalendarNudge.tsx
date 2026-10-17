// Home: one line when the calendar clashes with today's or tomorrow's training (calinsights.py),
// e.g. "Tempo run tomorrow clashes with a meeting". Tap opens Schedule on that day, where the
// "Your week vs your calendar" card has the one-tap fix. Hidden when there's nothing.
import { useEffect, useState } from 'react'
import { CalendarClock, ChevronRight } from 'lucide-react'
import { getCalInsights, type CalRec } from '@/lib/calinsights'
import { openPlanDay } from '@/lib/plancal'

export function CalendarNudge({ refreshKey }: { refreshKey?: number }) {
  const [rec, setRec] = useState<CalRec | null>(null)
  useEffect(() => {
    let live = true
    getCalInsights().then((d) => {
      if (!live || !d.connected || !d.today) return
      const t = new Date(`${d.today}T12:00:00`)
      t.setDate(t.getDate() + 1)
      const tomorrow = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
      setRec(d.recs.find((r) => r.kind !== 'long_day' && (r.date === d.today || r.date === tomorrow)) ?? null)
    }, () => { /* hidden on error */ })
    return () => { live = false }
  }, [refreshKey])
  if (!rec) return null
  return (
    <button type="button" onClick={() => openPlanDay(rec.date)}
      className="mx-4 mt-3 flex min-h-12 w-[calc(100%-2rem)] shrink-0 items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:opacity-80">
      <CalendarClock className="size-4 shrink-0 text-(--accent)" aria-hidden />
      <span className="min-w-0 flex-1 text-[0.8235rem] text-(--text)">{rec.title}</span>
      <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}
