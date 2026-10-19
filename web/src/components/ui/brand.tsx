// Shared look for every screen (see the design system note in styles/rabbit.css and CLAUDE.md):
// SectionLabel above a group, IconTile for a row's icon, Stat for a number with its label, and
// RabbitNote: the one surface for anything Rabbit says (chat replies use the same .rabbit-voice).
import type { ReactNode } from 'react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'

/** A heading over a group on a screen ("Your bests", "Recent workouts"): sentence case, 20px
 *  semibold (h2) or 17px inside sheets (h3/p). For a heading with a "See all" or a one-line
 *  description, use <Section> (components/ui/section.tsx). */
export function SectionLabel({ children, className, as: Tag = 'h2' }: { children: ReactNode; className?: string; as?: 'h2' | 'h3' | 'p' }) {
  return <Tag className={cn('section-title m-0 px-1', Tag !== 'h2' && 'section-title--sm', className)}>{children}</Tag>
}

/** A 40px rounded square holding a row's icon (accent tint by default). */
export function IconTile({ children, tone = 'accent', size = 40, className }: {
  children: ReactNode; tone?: 'accent' | 'neutral' | 'brand'; size?: number; className?: string
}) {
  return (
    <span aria-hidden style={{ width: size, height: size }}
      className={cn('flex shrink-0 items-center justify-center rounded-[12px]',
        tone === 'accent' && 'bg-(--accent-subtle) text-(--accent)',
        tone === 'neutral' && 'bg-(--bg-inset) text-(--text-secondary)',
        tone === 'brand' && 'logo-tile bg-(--brand) text-(--bg)', className)}>
      {children}
    </span>
  )
}

/** A number with a small label under it (key numbers, glance rows). */
export function Stat({ value, label, className }: { value: ReactNode; label: ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-w-0 flex-col', className)}>
      <span className="truncate font-mono text-title font-semibold tabular-nums text-(--text)">{value}</span>
      <span className="truncate text-small text-(--text-muted)">{label}</span>
    </div>
  )
}

/** Something Rabbit says outside the chat: same tinted surface and "Rabbit" label as its chat
 *  replies, with the rabbit mark, so the voice is recognisable everywhere. */
export function RabbitNote({ title = 'rabbt', children, className, compact }: {
  title?: string; children: ReactNode; className?: string; compact?: boolean
}) {
  return (
    <div className={cn('rabbit-voice flex gap-3', compact ? 'px-4 py-3' : 'px-4 py-4', className)}>
      <span className="logo-tile mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-(--brand)" aria-hidden>
        <RabbitLogo size={20} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5 text-body leading-snug">
        <p className="rabbit-voice__label m-0">{title}</p>
        {children}
      </div>
    </div>
  )
}
