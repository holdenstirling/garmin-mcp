// Rabbit's one status slot: a single row (at most 44px) for the most important thing to
// fix or see right now. Chat decides which one; this only draws it.
import { CalendarCheck, ChevronRight, ListChecks, Sparkles, Target, TriangleAlert, Watch, X } from 'lucide-react'
import { cn } from '@/lib/utils'

export type Banner =
  | { kind: 'error' }
  | { kind: 'garmin' }
  | { kind: 'plan'; goal: string | null }
  | { kind: 'quest'; title: string; done: number; total: number }
  | { kind: 'recap' }

const LOOK = {
  error: { icon: TriangleAlert, cls: 'border-(--danger)/30 bg-(--danger-subtle) text-(--danger)' },
  garmin: { icon: Watch, cls: 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning)' },
  plan: { icon: Sparkles, cls: 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' },
  quest: { icon: ListChecks, cls: 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' },
  recap: { icon: CalendarCheck, cls: 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' },
} as const

function text(b: Banner): string {
  switch (b.kind) {
    case 'error': return "Couldn't load your chats. Tap to retry."
    case 'garmin': return 'Connect Garmin so Rabbit can see your training'
    case 'plan': return b.goal ? `Build your plan for ${b.goal}` : 'Build your training plan'
    case 'quest': return `Setup ${b.done}/${b.total} · Next: ${b.title}`
    case 'recap': return 'Your week in review is ready'
  }
}

export function StatusBanner({ banner, onTap, onDismiss }: { banner: Banner; onTap: () => void; onDismiss?: () => void }) {
  const look = LOOK[banner.kind]
  const Icon = banner.kind === 'plan' && !banner.goal ? Target : look.icon
  return (
    <div className={cn('coach-pins mx-4 mt-2 flex h-11 shrink-0 items-center overflow-hidden rounded-xl border', look.cls)}
      role={banner.kind === 'error' ? 'alert' : undefined}>
      <button type="button" onClick={onTap} className="flex h-full min-w-0 flex-1 items-center gap-2 pl-3 pr-2 text-left">
        <Icon className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate text-[0.7647rem] font-medium">{text(banner)}</span>
        {!onDismiss && <ChevronRight className="size-4 shrink-0" />}
      </button>
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss" className="flex size-11 shrink-0 items-center justify-center opacity-70">
          <X className="size-4" />
        </button>
      )}
    </div>
  )
}
