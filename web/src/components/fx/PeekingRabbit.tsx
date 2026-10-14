// PeekingRabbit: for empty lists. A rabbit's ears and eyes pop up from behind an edge, one ear
// flicks, it blinks once. Plays once on mount; static (already peeking) with reduced motion.
import { cn } from '@/lib/utils'

export function PeekingRabbit({ size = 72, className }: { size?: number; className?: string }) {
  return (
    <span className={cn('fx-peek', className)} style={{ width: size, height: size * 0.62 }} aria-hidden="true">
      <svg viewBox="0 0 64 40" width={size} height={size * 0.62}>
        <g className="fx-peek__body">
          <g className="fx-peek__ear fx-peek__ear--l">
            <ellipse cx="24" cy="12" rx="5" ry="12" fill="var(--brand)" />
            <ellipse cx="24" cy="13" rx="2.3" ry="8" fill="var(--fx-ear)" />
          </g>
          <g className="fx-peek__ear fx-peek__ear--r">
            <ellipse cx="40" cy="12" rx="5" ry="12" fill="var(--brand)" />
            <ellipse cx="40" cy="13" rx="2.3" ry="8" fill="var(--fx-ear)" />
          </g>
          <ellipse cx="32" cy="40" rx="17" ry="14" fill="var(--brand)" />
          <g className="fx-peek__eyes">
            <circle cx="26" cy="33" r="2.1" fill="var(--bg-surface)" />
            <circle cx="38" cy="33" r="2.1" fill="var(--bg-surface)" />
          </g>
        </g>
      </svg>
      <span className="fx-peek__edge" />
    </span>
  )
}
