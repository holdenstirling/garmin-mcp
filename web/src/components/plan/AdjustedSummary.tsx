// Schedule: "rabbt adjusted N things this week", with each change and why, so a plan that
// bends around life (club runs, travel, sick days, readiness) says so in one place.
import { useState } from 'react'
import { ChevronDown, MessageCircle } from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { askRabbt } from '@/lib/askrabbt'
import { cn } from '@/lib/utils'
import type { BuiltPlan } from '@/lib/plan'
import { fmtDay } from './PlanParts'

export function AdjustedSummary({ plan, weekIndex }: { plan: BuiltPlan; weekIndex: number | null }) {
  const [open, setOpen] = useState(false)
  const w = plan.weeks.find((x) => x.index === (weekIndex ?? plan.current_week))
  if (!w) return null
  const items = w.days.flatMap((d) => d.sessions.filter((s) => s.why && s.why.kind !== 'you').map((s) => ({ d: d.date, s })))
  if (items.length === 0) return null
  const thisWeek = w.index === plan.current_week
  const n = items.length
  return (
    <div className="rounded-xl border border-(--border) bg-(--bg-surface)">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex min-h-12 w-full items-center gap-2.5 px-4 py-3 text-left">
        <RabbitLogo size={18} current className="shrink-0 text-(--accent)" />
        <span className="min-w-0 flex-1 text-body font-medium text-(--text)">
          rabbt adjusted {n} thing{n === 1 ? '' : 's'} {thisWeek ? 'this week' : `in week ${w.index}`}
        </span>
        <ChevronDown className={cn('size-5 shrink-0 text-(--text-muted) transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <ul className="flex flex-col gap-2 px-4 pb-3">
          {items.map(({ d, s }) => (
            <li key={s.id} className="flex flex-col gap-0.5">
              <span className="text-meta text-(--text-muted)">{fmtDay(d)}: {s.title}</span>
              <span className="text-small text-(--text-secondary)">{s.why!.text}</span>
            </li>
          ))}
          <li>
            <button type="button" onClick={() => askRabbt(`Why did my plan change ${thisWeek ? 'this week' : `in week ${w.index}`}? `)}
              className="inline-flex min-h-11 items-center gap-1 text-small font-semibold text-(--accent)">
              <MessageCircle className="size-4" aria-hidden /> Ask why
            </button>
          </li>
        </ul>
      )}
    </div>
  )
}
