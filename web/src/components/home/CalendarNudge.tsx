// Home: one line when the calendar clashes with today's or tomorrow's training (calinsights.py),
// e.g. "Tempo run tomorrow clashes with a meeting". Tap opens Schedule on that day, where the
// "Your week vs your calendar" card has the one-tap fix. Hidden when there's nothing.
import { useEffect, useState } from 'react'
import { CalendarClock, ChevronRight } from 'lucide-react'
import { getCalInsights, type CalRec } from '@/lib/calinsights'
import { openPlanDay } from '@/lib/plancal'

export function CalendarNudge({ refreshKey, onShown }: {
  refreshKey?: number
  /** after each load: whether the nudge shows (Home keeps one nudge up at a time) */
  onShown?: (shown: boolean) => void
}) {
  const [rec, setRec] = useState<CalRec | null>(null)
  useEffect(() => {
    let live = true
    getCalInsights().then((d) => {
      if (!live) return
      if (!d.connected || !d.today) { onShown?.(false); return }
      const t = new Date(`${d.today}T12:00:00`)
      t.setDate(t.getDate() + 1)
      const tomorrow = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
      const r = d.recs.find((x) => x.kind !== 'long_day' && (x.date === d.today || x.date === tomorrow)) ?? null
      setRec(r)
      onShown?.(!!r)
    }, () => { if (live) onShown?.(false) /* hidden on error */ })
    return () => { live = false }
  }, [refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!rec) return null
  return (
    <button type="button" onClick={() => openPlanDay(rec.date)}
      className="flex min-h-14 w-full shrink-0 items-center gap-3.5 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3.5 text-left active:opacity-80">
      <CalendarClock className="size-6 shrink-0 text-(--accent)" aria-hidden />
      <span className="min-w-0 flex-1 text-body leading-snug text-(--text)">{rec.title}</span>
      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}
