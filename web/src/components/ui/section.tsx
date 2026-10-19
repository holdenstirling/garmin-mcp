// Layout primitives for the "sections, not piles" rule (web/DESIGN.md):
//   * Section: a plain heading (sentence case, 20px semibold), an optional one-line description
//     and an optional "See all", then its content. Use it to group things on a screen instead of
//     wrapping everything in its own card.
//   * SeeAll: the right-hand link in a section heading.
//   * ListRow: one tappable row (icon, title, optional subtitle, trailing value or chevron), at
//     least 56px tall. Put rows in a <Card> (components/plan/ui.tsx) to get the dividers.
import { useId, type ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

export function Section({ title, description, action, children, className, as: Tag = 'h2', id, hideWhenEmpty }: {
  title: ReactNode
  /** one plain line under the heading: what this group is for */
  description?: ReactNode
  /** right of the heading, usually <SeeAll /> */
  action?: ReactNode
  children?: ReactNode
  className?: string
  as?: 'h2' | 'h3'
  id?: string
  /** hide the whole section (heading too) while every child renders nothing, e.g. cards that
   *  load their own data and hide themselves when there's nothing to show */
  hideWhenEmpty?: boolean
}) {
  const auto = useId()
  const hid = id ?? auto
  return (
    <section aria-labelledby={hid} className={cn('flex flex-col gap-3', hideWhenEmpty && 'section--hide-empty', className)}>
      <div className="flex items-end gap-3 px-1">
        <div className="min-w-0 flex-1">
          <Tag id={hid} className={cn('section-title m-0', Tag === 'h3' && 'section-title--sm')}>{title}</Tag>
          {description && <p className="m-0 mt-1 text-small leading-snug text-(--text-muted)">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function SeeAll({ onClick, label = 'See all', ariaLabel }: { onClick: () => void; label?: string; ariaLabel?: string }) {
  return (
    <button type="button" onClick={onClick} aria-label={ariaLabel}
      className="hit-44 inline-flex shrink-0 items-center gap-0.5 rounded-full text-body font-semibold text-(--accent) active:opacity-70">
      {label}<ChevronRight className="size-5" aria-hidden />
    </button>
  )
}

export function ListRow({ icon, title, subtitle, trailing, onClick, chevron = !!onClick, className, ariaLabel }: {
  icon?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  /** a value, a switch or a badge on the right */
  trailing?: ReactNode
  onClick?: () => void
  chevron?: boolean
  className?: string
  ariaLabel?: string
}) {
  const body = (
    <>
      {icon}
      <span className="min-w-0 flex-1">
        <span className="block text-body-lg font-medium leading-snug text-(--text)">{title}</span>
        {subtitle && <span className="mt-0.5 block text-small leading-snug text-(--text-muted)">{subtitle}</span>}
      </span>
      {trailing}
      {chevron && <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />}
    </>
  )
  const cls = cn('flex min-h-14 w-full items-center gap-3.5 px-4 py-3 text-left', className)
  return onClick
    ? <button type="button" onClick={onClick} aria-label={ariaLabel} className={cn(cls, 'active:bg-(--bg-inset)')}>{body}</button>
    : <div className={cls}>{body}</div>
}
