// EmptyRabbit: the empty-state illustration. The app's rabbit mark naps (a slow breathing
// bob with floating "z"s) or peeks up from behind a line, with optional title, body and
// action. The idle loop pauses when the tab is hidden or the art is offscreen; reduced
// motion shows it still. Only the RabbitLogo artwork is used.
import type { ReactNode } from 'react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'
import { useIdleLoop } from './useIdleLoop'

/** Just the art (a <span>, so it fits inside buttons). */
export function RabbitNap({ size = 56, mode = 'sleep', className }: { size?: number; mode?: 'sleep' | 'peek'; className?: string }) {
  const [ref, play] = useIdleLoop<HTMLSpanElement>()
  return (
    <span ref={ref} aria-hidden="true" className={cn('rb-nap', `rb-nap--${mode}`, !play && 'rb-paused', className)}
      style={{ width: size * 1.35, height: size }}>
      <span className="rb-nap__body"><RabbitLogo size={size} /></span>
      {mode === 'sleep' && <>
        <span className="rb-nap__z">z</span>
        <span className="rb-nap__z rb-nap__z--2">Z</span>
      </>}
      {mode === 'peek' && <span className="rb-nap__edge" />}
    </span>
  )
}

export function EmptyRabbit({ title, body, action, size = 56, mode = 'sleep', hero, className }: {
  title?: ReactNode
  body?: ReactNode
  action?: ReactNode
  size?: number
  mode?: 'sleep' | 'peek'
  /** display-font brand title (onboarding-style cards) */
  hero?: boolean
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center gap-2 text-center', className)}>
      <RabbitNap size={size} mode={mode} />
      {title && (hero
        ? <h2 className="font-display text-[1.1765rem] text-(--brand)">{title}</h2>
        : <p className="text-[0.8824rem] font-medium text-(--text)">{title}</p>)}
      {body && <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-muted)">{body}</p>}
      {action}
    </div>
  )
}
