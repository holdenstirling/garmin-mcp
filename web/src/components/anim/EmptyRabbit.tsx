// EmptyRabbit: the rabbit illustrations. The app's rabbit mark in one of a few poses, all
// drawn from the same mark plus small accents (no other artwork):
//   sleep  naps with floating "z"s (empty lists, rest days)
//   peek   peeks up from behind a line (empty states that invite an action)
//   run    bounds with speed lines (loading, "on the way")
//   cheer  hops with confetti (success, done)
//   think  tilts with a "?" bubble (errors, "couldn't find that")
//   wave   sways with a little "hi" (onboarding, first visit)
//   offline  dims under a cloud (no connection)
// With optional title, body and action. The idle loop pauses when the tab is hidden or the art is offscreen; reduced
// motion shows it still. Only the RabbitLogo artwork is used.
import type { ReactNode } from 'react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'
import { useIdleLoop } from './useIdleLoop'

/** Just the art (a <span>, so it fits inside buttons). */
export type RabbitPose = 'sleep' | 'peek' | 'run' | 'cheer' | 'think' | 'wave' | 'offline'

export function RabbitNap({ size = 56, mode = 'sleep', className }: { size?: number; mode?: RabbitPose; className?: string }) {
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
      {mode === 'run' && <span className="rb-pose__lines"><i /><i /><i /></span>}
      {mode === 'cheer' && <span className="rb-pose__confetti"><i /><i /><i /><i /></span>}
      {mode === 'think' && <span className="rb-pose__bubble">?</span>}
      {mode === 'wave' && <span className="rb-pose__hi">hi!</span>}
      {mode === 'offline' && (
        <svg className="rb-pose__cloud" viewBox="0 0 24 24" width={size * 0.42} height={size * 0.42} fill="none" stroke="currentColor"
          strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" /><path d="m2 2 20 20" />
        </svg>
      )}
    </span>
  )
}

export function EmptyRabbit({ title, body, action, size = 56, mode = 'sleep', hero, className }: {
  title?: ReactNode
  body?: ReactNode
  action?: ReactNode
  size?: number
  mode?: RabbitPose
  /** display-font brand title (onboarding-style cards) */
  hero?: boolean
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center gap-2 text-center', className)}>
      <RabbitNap size={size} mode={mode} />
      {title && (hero
        ? <h3 className="font-display text-[1.1765rem] text-(--brand)">{title}</h3>
        : <p className="text-[0.8824rem] font-medium text-(--text)">{title}</p>)}
      {body && <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-muted)">{body}</p>}
      {action}
    </div>
  )
}
