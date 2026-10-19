// The workout icon: the sport's line icon on its own tint (one color per family of sports, set
// in globals.css as --sport-<tone>), the same everywhere a workout shows up. Decorative: put the
// sport's name in text next to it (or pass ``label`` when there's no visible text).
import type { CSSProperties } from 'react'
import { Check } from 'lucide-react'
import { familyIcon, familyTone, sportIcon } from '@/lib/sportIcon'
import { sportFamily, type SportFamily } from '@/lib/sportstats'
import { cn } from '@/lib/utils'

export function SportTile({ sport, kind, family, size = 40, label, done, className }: {
  sport?: string | null
  /** Garmin's type ("indoor_cycling", "yoga") when known */
  kind?: string | null
  family?: SportFamily | string | null
  /** px; the icon is about half of it */
  size?: number
  /** an accessible name when no text next to it says the sport */
  label?: string
  /** a small check in the corner for a finished session */
  done?: boolean
  className?: string
}) {
  const fam = sportFamily(family || sport, family ? null : kind)
  const s = (sport ?? '').toLowerCase()
  const Icon = s === 'rest' || s === 'race' ? sportIcon(s) : familyIcon(fam)
  const tone = s === 'rest' ? 'other' : familyTone(fam)
  const style = { width: size, height: size, '--tile-fg': `var(--sport-${tone})`, '--tile-bg': `var(--sport-${tone}-bg)` } as CSSProperties
  return (
    <span role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true} style={style}
      className={cn('relative inline-flex shrink-0 items-center justify-center rounded-lg bg-(--tile-bg) text-(--tile-fg)', className)}>
      <Icon style={{ width: Math.round(size * 0.52), height: Math.round(size * 0.52) }} strokeWidth={2} aria-hidden />
      {done && (
        <span aria-hidden className="absolute -bottom-1 -right-1 flex size-[18px] items-center justify-center rounded-full bg-(--accent) text-(--on-fill) ring-2 ring-(--bg-surface)">
          <Check className="size-3" strokeWidth={3} />
        </span>
      )}
    </span>
  )
}
