/**
 * RabbitLoader: the RabbitLogo mark running in place. It bounds with a stride (hop, lean,
 * squash on landing) over a ground line that scrolls left, kicking up dust behind its feet.
 * ``label`` is shown under it (and names the status); with ``cycle`` the rotating messages
 * show instead and ``label`` stays the accessible name. ``inline`` is a compact row for small
 * spots; ``decorative`` drops the status role for idle, purely visual use (sign-in); ``gentle``
 * slows the stride.
 * Animations live in globals.css (.rabbit-loader*) with a reduced-motion fallback.
 */
import { useEffect, useState, type CSSProperties } from 'react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'

const CYCLE_MS = 1800

export function RabbitLoader({ size, label, cycle, className, inline = false, decorative = false, gentle = false }: {
  size?: number
  label?: string
  cycle?: string[]
  className?: string
  inline?: boolean
  decorative?: boolean
  gentle?: boolean
}) {
  const px = size ?? (inline ? 20 : 56)
  const [i, setI] = useState(0)
  const count = cycle?.length ?? 0

  useEffect(() => {
    if (count < 2) return
    const id = window.setInterval(() => setI((n) => (n + 1) % count), CYCLE_MS)
    return () => window.clearInterval(id)
  }, [count])

  // Rotating messages are flavor: hidden from screen readers so the live region isn't chatty.
  const rotating = count > 0 ? cycle![i % count] : undefined
  const text = rotating ?? label
  const style = { '--rl-size': `${px}px` } as CSSProperties
  const a11y = decorative
    ? { 'aria-hidden': true as const }
    : { role: 'status', 'aria-live': 'polite' as const, 'aria-label': label ?? 'Loading' }

  if (inline) {
    return (
      <span {...a11y} style={style}
        className={cn('rabbit-loader rabbit-loader--inline', gentle && 'rabbit-loader--gentle', className)}>
        <span className="rabbit-loader__runner" aria-hidden="true"><RabbitLogo size={px} /></span>
        {text && <span key={rotating ? i : undefined} className="rabbit-loader__msg" aria-hidden={rotating ? true : undefined}>{text}</span>}
      </span>
    )
  }

  return (
    <div {...a11y} style={style}
      className={cn('rabbit-loader', gentle && 'rabbit-loader--gentle', className)}>
      <div className="rabbit-loader__stage" aria-hidden="true">
        <span className="rabbit-loader__ground" />
        <span className="rabbit-loader__dust"><i /><i /><i /></span>
        <span className="rabbit-loader__runner"><RabbitLogo size={px} /></span>
      </div>
      {text && (
        <p key={rotating ? i : undefined} className={rotating ? 'rabbit-loader__msg' : 'rabbit-loader__label'}
          aria-hidden={rotating ? true : undefined}>
          {text}
        </p>
      )}
    </div>
  )
}
