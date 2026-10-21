// Rabbit's one status slot: a single row (at most 44px) for the most important thing to
// fix or see right now. Chat decides which one; this only draws it.
import type React from 'react'
import { CalendarCheck, ChevronRight, ListChecks, Route, Target, TriangleAlert, Watch, X } from 'lucide-react'
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
  plan: { icon: Route, cls: 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' },
  quest: { icon: ListChecks, cls: 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' },
  recap: { icon: CalendarCheck, cls: 'border-(--accent)/30 bg-(--accent-subtle) text-(--accent)' },
} as const

function text(b: Banner): string {
  switch (b.kind) {
    case 'error': return "Couldn't load your chats. Tap to retry."
    case 'garmin': return 'Connect Garmin so rabbt can see your training'
    case 'plan': return b.goal ? `Get a plan for ${b.goal}` : 'Get a training plan'
    case 'quest': return `Next: ${b.title}`
    case 'recap': return 'Your week in review is ready'
  }
}

/** Small done/total ring for the setup pill; the count sits inside. Decorative: the button
 *  carries the spoken "Setup 2 of 6" label. */
function SetupRing({ done, total }: { done: number; total: number }) {
  const r = 12, c = 2 * Math.PI * r
  const frac = total > 0 ? Math.min(1, done / total) : 0
  return (
    <span className="relative inline-flex size-10 shrink-0 items-center justify-center" aria-hidden>
      <svg viewBox="0 0 28 28" className="absolute inset-0 size-10 -rotate-90">
        <circle cx="14" cy="14" r={r} fill="none" stroke="currentColor" strokeOpacity={0.2} strokeWidth={2.5} />
        <circle cx="14" cy="14" r={r} fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round"
          className="rb-ring" strokeDasharray={c} strokeDashoffset={c * (1 - frac)} style={{ '--rb-ring': c } as React.CSSProperties} />
      </svg>
      <span className="text-caption font-semibold leading-none tabular-nums">{done}/{total}</span>
    </span>
  )
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
      <button type="button" onClick={onTap} className={cn('flex min-w-0 flex-1 items-center text-left', flush ? 'min-h-14 gap-3 py-3 pl-4 pr-3' : 'h-full gap-2 pl-3 pr-2')}
        aria-label={banner.kind === 'quest' ? `Setup ${banner.done} of ${banner.total}. Next: ${banner.title}` : undefined}>
        {banner.kind === 'quest' ? <SetupRing done={banner.done} total={banner.total} /> : <Icon className="size-5 shrink-0" />}
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
