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
    case 'garmin': return 'Connect Garmin so Rabbit can see your training'
    case 'plan': return b.goal ? `Build your plan for ${b.goal}` : 'Build your training plan'
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
    <span className="relative inline-flex size-7 shrink-0 items-center justify-center" aria-hidden>
      <svg viewBox="0 0 28 28" className="absolute inset-0 size-7 -rotate-90">
        <circle cx="14" cy="14" r={r} fill="none" stroke="currentColor" strokeOpacity={0.2} strokeWidth={2.5} />
        <circle cx="14" cy="14" r={r} fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round"
          className="rb-ring" strokeDasharray={c} strokeDashoffset={c * (1 - frac)} style={{ '--rb-ring': c } as React.CSSProperties} />
      </svg>
      <span className="font-mono text-[0.6471rem] font-medium leading-none tabular-nums">{done}/{total}</span>
    </span>
  )
}

export function StatusBanner({ banner, onTap, onDismiss }: { banner: Banner; onTap: () => void; onDismiss?: () => void }) {
  const look = LOOK[banner.kind]
  const Icon = banner.kind === 'plan' && !banner.goal ? Target : look.icon
  return (
    <div className={cn('coach-pins mx-4 mt-2 flex h-12 shrink-0 items-center overflow-hidden rounded-xl border', look.cls)}
      role={banner.kind === 'error' ? 'alert' : undefined}>
      <button type="button" onClick={onTap} className="flex h-full min-w-0 flex-1 items-center gap-2 pl-3 pr-2 text-left"
        aria-label={banner.kind === 'quest' ? `Setup ${banner.done} of ${banner.total}. Next: ${banner.title}` : undefined}>
        {banner.kind === 'quest' ? <SetupRing done={banner.done} total={banner.total} /> : <Icon className="size-4 shrink-0" />}
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
