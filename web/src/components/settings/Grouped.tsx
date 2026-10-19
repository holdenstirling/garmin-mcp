// iOS-style grouped list for Me, Settings and sheets: a plain heading (sentence case, readable,
// web/DESIGN.md "sections, not piles"), an optional one-line description, a rounded group of
// rows separated by hairlines, and an optional footnote under the group.
import { createContext, useContext } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Wrap a full page of groups (Me, Settings) so every Group heading is a 20px section title. */
export const LargeGroups = createContext(false)

export function Group({ label, description, footer, children, large }: {
  label?: string
  /** one plain line under the heading: what this group is for */
  description?: React.ReactNode
  footer?: React.ReactNode; children: React.ReactNode
  /** a screen-level section heading (20px) instead of the 17px group heading (sheets) */
  large?: boolean
}) {
  const pageLevel = useContext(LargeGroups)
  large = large ?? pageLevel
  return (
    <section className="flex flex-col gap-2.5">
      {(label || description) && (
        <div className="px-1">
          {label && <h2 className={cn('section-title m-0', !large && 'section-title--sm')}>{label}</h2>}
          {description && <p className="m-0 mt-1 text-small leading-snug text-(--text-secondary)">{description}</p>}
        </div>
      )}
      <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">{children}</div>
      {footer && <div className="px-1 text-small leading-snug text-(--text-secondary)">{footer}</div>}
    </section>
  )
}

export function Icon({ children, tone = 'accent' }: { children: React.ReactNode; tone?: 'accent' | 'danger' | 'muted' }) {
  return (
    <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg [&>svg]:size-5',
      tone === 'accent' ? 'bg-(--accent-subtle) text-(--accent)'
        : tone === 'danger' ? 'bg-(--danger-subtle) text-(--danger)'
        : 'bg-(--bg-inset) text-(--text-secondary)')}>
      {children}
    </span>
  )
}

/** One row. Clickable when `onClick` is set (chevron unless `trailing` is given). */
export function Row({ icon, title, subtitle, trailing, onClick, danger, disabled, center }: {
  icon?: React.ReactNode; title: React.ReactNode; subtitle?: React.ReactNode
  trailing?: React.ReactNode; onClick?: () => void; danger?: boolean; disabled?: boolean; center?: boolean
}) {
  const body = (
    <>
      {icon}
      <span className={cn('min-w-0 flex-1', center && 'text-center')}>
        <span className={cn('block text-body-lg font-medium leading-snug', danger ? 'text-(--danger)' : 'text-(--text)')}>{title}</span>
        {subtitle && <span className="mt-0.5 block text-small leading-snug text-(--text-secondary)">{subtitle}</span>}
      </span>
      {trailing ?? (onClick && !center && <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />)}
    </>
  )
  const cls = 'settings-row flex min-h-14 w-full items-center gap-3.5 px-4 py-3 text-left'
  return onClick ? (
    <button type="button" onClick={onClick} disabled={disabled}
      className={cn(cls, 'transition-colors active:bg-(--bg-inset) disabled:opacity-50')}>{body}</button>
  ) : <div className={cls}>{body}</div>
}

export function Switch({ checked, onChange, label, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn('hit-44 relative h-[31px] w-[51px] shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50',
        checked ? 'bg-(--accent)' : 'bg-(--bg-inset)')}>
      <span className={cn('absolute top-[2px] left-[2px] size-[27px] rounded-full bg-white shadow-md transition-transform duration-200',
        checked && 'translate-x-[20px]')} />
    </button>
  )
}
