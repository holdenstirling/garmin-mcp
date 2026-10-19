// A titled list of rows for the social and Local screens: a plain section heading (20px,
// sentence case) with an optional line under it and an optional "See all", then the rows in one
// card with hairlines between them (the `settings-group` look), and an optional footnote.
import type { ReactNode } from 'react'
import { Section } from '@/components/ui/section'

export function RowGroup({ title, description, action, footer, children, as = 'h2' }: {
  title?: ReactNode; description?: ReactNode; action?: ReactNode; footer?: ReactNode; children: ReactNode; as?: 'h2' | 'h3'
}) {
  if (!title) {
    return (
      <div className="flex flex-col gap-3">
        <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">{children}</div>
        {footer && <div className="px-1 text-small leading-snug text-(--text-muted)">{footer}</div>}
      </div>
    )
  }
  return (
    <Section title={title} description={description} action={action} as={as}>
      <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">{children}</div>
      {footer && <div className="px-1 text-small leading-snug text-(--text-muted)">{footer}</div>}
    </Section>
  )
}
