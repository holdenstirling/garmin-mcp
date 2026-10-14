// Declarative CarrotBurst: ``<CarrotBurst trigger={n} kind="kudos">{button}</CarrotBurst>``
// fires one burst (carrots, hop prints, sparkles) from its own spot each time ``trigger``
// changes to a truthy value (never on mount with a falsy trigger). The burst itself is the
// shared fx one (one at a time, portaled, haptic tap, off with reduced motion). Imperative:
// ``burst(el | {x, y}, kind)``.
import { useEffect, useRef, type ReactNode } from 'react'
import { celebrate, type BurstKind } from '@/components/fx/motion'
import { cn } from '@/lib/utils'

export const burst = celebrate

export function CarrotBurst({ trigger, kind = 'xp', delay = 0, className, children }: {
  trigger: unknown; kind?: BurstKind; delay?: number; className?: string; children?: ReactNode
}) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!trigger) return
    const t = window.setTimeout(() => celebrate(ref.current, kind), delay)
    return () => window.clearTimeout(t)
  }, [trigger]) // eslint-disable-line react-hooks/exhaustive-deps
  return <span ref={ref} className={cn('inline-flex', className)}>{children}</span>
}
