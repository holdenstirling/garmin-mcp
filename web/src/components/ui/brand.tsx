// Shared look for every screen (see the design system note in styles/rabbit.css and CLAUDE.md):
// SectionLabel above a group, IconTile for a row's icon, Stat for a number with its label, and
// RabbitNote: the one surface for anything Rabbit says (chat replies use the same .rabbit-voice).
import type { ReactNode } from 'react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'

export function SectionLabel({ children, className, as: Tag = 'h2' }: { children: ReactNode; className?: string; as?: 'h2' | 'h3' | 'p' }) {
  return <Tag className={cn('section-label m-0 px-1', className)}>{children}</Tag>
}

/** A 36px rounded square holding a row's icon (accent tint by default). */
export function IconTile({ children, tone = 'accent', size = 36, className }: {
  children: ReactNode; tone?: 'accent' | 'neutral' | 'brand'; size?: number; className?: string
}) {
  return (
    <span aria-hidden style={{ width: size, height: size }}
      className={cn('flex shrink-0 items-center justify-center rounded-lg',
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
    <div className={cn('rabbit-voice flex gap-2.5', compact ? 'px-3 py-2.5' : 'px-3.5 py-3', className)}>
      <span className="logo-tile mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-(--brand)" aria-hidden>
        <RabbitLogo size={18} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1 text-meta leading-snug">
        <p className="rabbit-voice__label m-0">{title}</p>
        {children}
      </div>
    </div>
  )
}
