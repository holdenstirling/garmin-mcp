// Small building blocks for the plan screens, in Rabbit's existing look: grouped cards,
// DM Mono labels, forest-green accent chips.
import { ChevronLeft, Minus, Plus, X } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Full-screen page that slides up over the app (setup wizard, plan editor). */
export function Screen({ title, subtitle, onBack, onClose, closing, footer, children, headerExtra }: {
  title: string; subtitle?: string
  onBack?: () => void; onClose: () => void; closing?: boolean
  footer?: React.ReactNode; children: React.ReactNode; headerExtra?: React.ReactNode
}) {
  return (
    <div className={cn('plan-screen', closing && 'plan-screen--exit')} role="dialog" aria-modal aria-label={title}>
      <header className="shrink-0 border-b border-(--border) bg-(--bg) px-3 pb-2.5 pt-[max(10px,env(safe-area-inset-top))]">
        <div className="flex items-center gap-2">
          {onBack ? (
            <button className="modal-close" aria-label="Back" onClick={onBack}><ChevronLeft className="size-5" /></button>
          ) : <span className="w-8" />}
          <div className="min-w-0 flex-1 text-center">
            <h2 className="truncate font-display text-[1.0588rem] leading-tight text-(--brand)">{title}</h2>
            {subtitle && <p className="truncate text-[0.6471rem] text-(--text-muted)">{subtitle}</p>}
          </div>
          <button className="modal-close" aria-label="Close" onClick={onClose}><X className="size-4" /></button>
        </div>
        {headerExtra}
      </header>
      <div className="settings min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="mx-auto flex w-full max-w-xl flex-col gap-5 px-4 py-5">{children}</div>
      </div>
      {footer && (
        <footer className="shrink-0 border-t border-(--border) bg-(--bg) px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          <div className="mx-auto flex w-full max-w-xl gap-2">{footer}</div>
        </footer>
      )}
    </div>
  )
}

export function Progress({ step, total }: { step: number; total: number }) {
  return (
    <div className="mx-auto mt-2.5 flex max-w-xl gap-1 px-1" aria-label={`Step ${step + 1} of ${total}`}>
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className={cn('h-1 flex-1 rounded-full transition-colors duration-300',
          i <= step ? 'bg-(--accent)' : 'bg-(--bg-elevated)')} />
      ))}
    </div>
  )
}

/** Big friendly heading at the top of a wizard step. */
export function StepIntro({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="px-1">
      <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">{eyebrow}</p>
      <h3 className="mt-1 font-display text-[1.4118rem] leading-tight text-(--brand)">{title}</h3>
      {children && <p className="mt-1.5 text-[0.8235rem] leading-snug text-(--text-secondary)">{children}</p>}
    </div>
  )
}

/** A labeled block inside a card. */
export function Field({ label, hint, children, className }: {
  label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-2 px-4 py-3.5', className)}>
      <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{label}</span>
      {children}
      {hint && <span className="text-[0.7059rem] leading-snug text-(--text-muted)">{hint}</span>}
    </div>
  )
}

export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)', className)}>{children}</div>
}

export function Chip({ selected, onClick, children, disabled, title }: {
  selected?: boolean; onClick?: () => void; children: React.ReactNode; disabled?: boolean; title?: string
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-pressed={selected} title={title}
      className={cn('plan-chip', selected && 'plan-chip--on')}>
      {children}
    </button>
  )
}

export function ChipRow({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap gap-2">{children}</div>
}

/** One-of chips. */
export function Choice<T extends string>({ value, options, onChange, allowNone }: {
  value: T | null | undefined; options: readonly (readonly [T, string])[] | [T, string][]
  onChange: (v: T | null) => void; allowNone?: boolean
}) {
  return (
    <ChipRow>
      {options.map(([v, label]) => (
        <Chip key={v} selected={value === v} onClick={() => onChange(allowNone && value === v ? null : v)}>{label}</Chip>
      ))}
    </ChipRow>
  )
}

/** Any-of chips. */
export function MultiChoice<T extends string>({ value, options, onChange }: {
  value: T[]; options: readonly (readonly [T, string])[]; onChange: (v: T[]) => void
}) {
  return (
    <ChipRow>
      {options.map(([v, label]) => (
        <Chip key={v} selected={value.includes(v)}
          onClick={() => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])}>{label}</Chip>
      ))}
    </ChipRow>
  )
}

/** Big card-like option with a description (experience level, goal type). */
export function OptionCard({ selected, title, description, onClick }: {
  selected: boolean; title: string; description: string; onClick: () => void
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected}
      className={cn('flex w-full flex-col items-start gap-0.5 rounded-xl border px-3.5 py-3 text-left transition-colors',
        selected ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface) active:bg-(--bg-inset)')}>
      <span className={cn('text-[0.9412rem] font-medium', selected ? 'text-(--accent)' : 'text-(--text)')}>{title}</span>
      <span className="text-[0.7647rem] leading-snug text-(--text-muted)">{description}</span>
    </button>
  )
}

export function NumberStepper({ value, onChange, step = 1, min, max, suffix, decimals = 0, label }: {
  value: number | null | undefined; onChange: (v: number | null) => void
  step?: number; min: number; max: number; suffix?: string; decimals?: number; label: string
}) {
  const v = value ?? null
  const bump = (d: number) => {
    const base = v ?? Math.round(((min + max) / 2) / step) * step
    const next = Math.min(max, Math.max(min, Math.round((base + d) * 10 ** decimals) / 10 ** decimals))
    onChange(next)
  }
  return (
    <div className="flex items-center gap-2">
      <button type="button" className="plan-step-btn" aria-label={`Less ${label}`} onClick={() => bump(-step)}><Minus className="size-4" /></button>
      <div className="flex flex-1 items-baseline justify-center gap-1">
        <input inputMode="decimal" aria-label={label} value={v ?? ''} placeholder="–"
          onChange={(e) => {
            const t = e.target.value.replace(',', '.')
            if (t === '') return onChange(null)
            const n = Number(t)
            if (Number.isFinite(n)) onChange(n)
          }}
          className="w-20 bg-transparent text-center font-display text-[1.6471rem] leading-none text-(--text) outline-none placeholder:text-(--text-muted)" />
        {suffix && <span className="text-[0.7647rem] text-(--text-muted)">{suffix}</span>}
      </div>
      <button type="button" className="plan-step-btn" aria-label={`More ${label}`} onClick={() => bump(step)}><Plus className="size-4" /></button>
    </div>
  )
}

export const inputCls = 'h-10 w-full rounded-md border border-input bg-transparent px-3 text-base text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'
export const areaCls = 'min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-base text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'
