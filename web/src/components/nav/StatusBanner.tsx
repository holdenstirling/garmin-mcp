// Rabbit's one status slot: a single row (at most 44px) for the most important thing to
// fix or see right now. Chat decides which one; this only draws it.
import { CalendarCheck, ChevronRight, Route, Target, TriangleAlert, Watch, X } from 'lucide-react'
import { cn } from '@/lib/utils'

export type Banner =
  | { kind: 'error' }
  | { kind: 'garmin' }
  | { kind: 'plan'; goal: string | null }
  | { kind: 'recap' }

const LOOK = {
  error: { icon: TriangleAlert, cls: 'border-(--danger)/30 bg-(--danger-subtle) text-(--danger)' },
  garmin: { icon: Watch, cls: 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning)' },
  plan: { icon: Route, cls: 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' },
  recap: { icon: CalendarCheck, cls: 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' },
} as const

function text(b: Banner): string {
  switch (b.kind) {
    case 'error': return "Couldn't load your chats. Tap to retry."
    case 'garmin': return 'Connect your watch so rabbt can see your training'
    case 'plan': return b.goal ? `Get a plan for ${b.goal}` : 'Get a training plan'
    case 'recap': return 'Your week in review is ready'
  }
}

export function StatusBanner({ banner, onTap, onDismiss, flush }: {
  banner: Banner; onTap: () => void; onDismiss?: () => void
  /** Home's nudge slot: no outer margins, a roomier row and text that wraps */
  flush?: boolean
}) {
  const look = LOOK[banner.kind]
  const Icon = banner.kind === 'plan' && !banner.goal ? Target : look.icon
  return (
    <div className={cn('coach-pins flex shrink-0 items-center overflow-hidden rounded-xl border', flush ? 'min-h-14' : 'mx-4 mt-2 h-12', look.cls)}
      role={banner.kind === 'error' ? 'alert' : undefined}>
      <button type="button" onClick={onTap} className={cn('flex min-w-0 flex-1 items-center text-left', flush ? 'min-h-14 gap-3 py-3 pl-4 pr-3' : 'h-full gap-2 pl-3 pr-2')}>
        <Icon className="size-5 shrink-0" />
        <span className={cn('min-w-0 flex-1 font-medium', flush ? 'text-body leading-snug' : 'truncate text-small')}>{text(banner)}</span>
        {!onDismiss && <ChevronRight className="size-5 shrink-0" />}
      </button>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss" className="flex size-11 shrink-0 items-center justify-center opacity-70">
          <X className="size-5" />
        </button>
      )}
    </div>
  )
}
