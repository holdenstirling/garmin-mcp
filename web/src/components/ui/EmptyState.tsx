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
    <div className={cn('flex flex-col items-center text-center', compact ? 'gap-2 px-4 py-6' : 'gap-2.5 px-6 py-10',
      card && 'rounded-2xl border border-(--border) bg-(--bg-surface)', className)}>
      {icon ? (
        <span aria-hidden className="flex size-14 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)">{icon}</span>
      ) : <RabbitNap size={compact ? 44 : 56} mode={mode} />}
      <p className={cn('font-display leading-tight text-(--brand)', compact ? 'text-[1.0588rem]' : 'text-[1.1765rem]')}>{title}</p>
      {body && <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-secondary)">{body}</p>}
      {action && onAction && (
        <button type="button" onClick={onAction}
          className="mt-1 min-h-11 rounded-full bg-(--accent) px-5 text-[0.8235rem] font-semibold text-(--on-fill) active:opacity-80">
          {action}
        </button>
      )}
      {secondary && onSecondary && (
        <button type="button" onClick={onSecondary} className="min-h-11 px-3 text-[0.7647rem] font-medium text-(--accent)">
          {secondary}
        </button>
      )}
    </div>
  )
}
