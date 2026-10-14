// HopIn: children enter with a small hop (rise + scale, a touch of overshoot). ``index``
// staggers lists and cards (40 ms apart, capped so the last one still starts within 240 ms).
// Plays once on mount; keyed items that stay mounted never replay. Nothing with reduced motion.
import { createElement, type CSSProperties, type HTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

const STEP = 40
const MAX_STEPS = 6

/** Spread onto an existing element instead of wrapping it: ``<div {...hopIn(i)} />``. */
export function hopIn(index = 0, className?: string, style?: CSSProperties): { className: string; style: CSSProperties } {
  return {
    className: cn('rb-hop-in', className),
    style: { ...style, animationDelay: `${Math.min(Math.max(0, index), MAX_STEPS) * STEP}ms` },
  }
}

export function HopIn({ index = 0, as = 'div', play = true, className, style, children, ...rest }: {
  index?: number
  as?: 'div' | 'section' | 'li' | 'span' | 'article'
  /** false renders the children without the entrance (e.g. not the first view today) */
  play?: boolean
  children?: ReactNode
} & HTMLAttributes<HTMLElement>) {
  const p = play ? hopIn(index, className, style) : { className, style }
  return createElement(as, { ...rest, ...p }, children)
}
