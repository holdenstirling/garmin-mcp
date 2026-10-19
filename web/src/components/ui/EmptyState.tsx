// The one empty screen: Rabbit napping or peeking (components/anim RabbitNap), a title, one
// plain line and (usually) one clear next step as a real button. Use it wherever a list has
// nothing in it yet, instead of a bare sentence.
import { RabbitNap, type RabbitPose } from '@/components/anim'
import { cn } from '@/lib/utils'

export function EmptyState({ title, body, action, onAction, secondary, onSecondary, icon, mode = 'peek', compact, card, className }: {
  title: string
  body?: React.ReactNode
  /** the one primary action */
  action?: string
  onAction?: () => void
  secondary?: string
  onSecondary?: () => void
  /** replaces Rabbit (a lucide icon element) */
  icon?: React.ReactNode
  /** which rabbit: peek (default), sleep, run, cheer, think, wave, offline */
  mode?: RabbitPose
  /** inside a card or sheet: less padding, smaller art */
  compact?: boolean
  /** draw its own card */
  card?: boolean
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center text-center', compact ? 'gap-2.5 px-5 py-7' : 'gap-3 px-6 py-12',
      card && 'rounded-2xl border border-(--border) bg-(--bg-surface)', className)}>
      {icon ? (
        <span aria-hidden className="flex size-14 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)">{icon}</span>
      ) : <RabbitNap size={compact ? 44 : 56} mode={mode} />}
      <p className={cn('font-display leading-tight text-(--brand)', compact ? 'text-title-sm' : 'text-title')}>{title}</p>
      {body && <p className="max-w-xs text-body leading-snug text-(--text-secondary)">{body}</p>}
      {action && onAction && (
        <button type="button" onClick={onAction}
          className="mt-2 min-h-12 rounded-full bg-(--accent) px-6 text-body font-semibold text-(--on-fill) active:opacity-80">
          {action}
        </button>
      )}
      {secondary && onSecondary && (
        <button type="button" onClick={onSecondary} className="min-h-11 px-3 text-body font-medium text-(--accent)">
          {secondary}
        </button>
      )}
    </div>
  )
}
