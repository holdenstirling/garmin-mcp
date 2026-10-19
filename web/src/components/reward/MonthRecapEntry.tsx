// Progress -> one row: last month's share card (MonthRecapSheet). Brighter in the first week
// of a month, when the card is new.
import { CalendarHeart, ChevronRight } from 'lucide-react'
import { lastMonth } from '@/lib/reward'
import { cn } from '@/lib/utils'

export function MonthRecapEntry({ onOpen }: { onOpen: (month: string) => void }) {
  const { month, label } = lastMonth()
  const fresh = new Date().getDate() <= 7
  return (
    <button type="button" onClick={() => onOpen(month)}
      className={cn('mx-auto mb-3 flex min-h-11 w-full max-w-xl items-center gap-3 rounded-xl border px-3 py-2 text-left active:opacity-80',
        fresh ? 'border-(--accent)/40 bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
      <CalendarHeart className="size-5 shrink-0 text-(--accent)" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block text-body font-semibold text-(--text)">Your {label}</span>
        <span className="block text-small text-(--text-secondary)">{fresh ? 'Your month card is ready to share' : 'Month in review · share card'}</span>
      </span>
      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden="true" />
    </button>
  )
}
