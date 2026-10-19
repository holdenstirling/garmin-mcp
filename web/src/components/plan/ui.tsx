// Small building blocks for the plan screens, in Rabbit's existing look: grouped cards,
// DM Mono labels, forest-green accent chips.
import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronLeft, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useDialog } from '@/hooks/useDialog'
import { RabbitLogo } from '@/components/RabbitLogo'

// Tab pages (components/nav): a TabScreen hosts one embedded page. The page is the first
// Screen that *commits* inside it (claimed in a layout effect, never during render: a render
// can be retried or thrown away, e.g. while React.lazy suspends, and a thrown-away render must
// not leave a stale claim behind). The page has no close button, no slide and sits above the
// tab bar. Every other Screen stays a full-screen overlay: siblings opened next to the page
// (event editor, race pack) lose the claim, and anything rendered inside a Screen never sees
// the tab at all (the Screen resets the context for its children).
type Embed = { claim: { owner: string | null }; title?: string; top?: React.ReactNode; lead?: React.ReactNode; action?: React.ReactNode }
const EmbedCtx = createContext<Embed | null>(null)

export function TabScreen({ title, top, lead, action, children }: {
  /** replaces the embedded screen's own title */
  title?: string
  /** right of the title (the Me avatar) */
  action?: React.ReactNode
  /** under the title, above the screen's own header extras (segmented control) */
  top?: React.ReactNode
  /** first thing in the scrolling body */
  lead?: React.ReactNode
  children: React.ReactNode
}) {
  const claim = useRef<{ owner: string | null }>({ owner: null }).current
  return <EmbedCtx.Provider value={{ claim, title, top, lead, action }}>{children}</EmbedCtx.Provider>
}

// Page stack (screens/Chat.tsx): a page pushed from another page gets `back` (one level) from
// PageStack and keeps its own onClose (the whole stack). A Screen opened inside an overlay
// Screen is a child page too: with no onBack of its own its close becomes a back arrow.
type Stack = { back?: () => void; nested?: boolean }
const StackCtx = createContext<Stack | null>(null)
const NESTED: Stack = { nested: true }
export function PageStack({ back, children }: { back?: () => void; children: React.ReactNode }) {
  return <StackCtx.Provider value={back ? { back } : null}>{children}</StackCtx.Provider>
}

/** Full-screen page that slides up over the app (setup wizard, plan editor), or a tab page
 *  inside a TabScreen. Close model: a child screen whose back is its close (onBack === onClose)
 *  shows only a back arrow, a root screen only an X, a screen with a separate back step and
 *  close (wizard step, inbox thread) both, and a tab page neither. `onClose` is optional only for screens that
 *  are always a tab page: a Screen without a close action never shows an X. */
export function Screen({ title, subtitle, onBack, onClose, closing, footer, children, headerExtra }: {
  title: string; subtitle?: string
  onBack?: () => void; onClose?: () => void; closing?: boolean
  footer?: React.ReactNode; children: React.ReactNode; headerExtra?: React.ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const none = useRef<HTMLDivElement>(null)
  const id = useId()
  const embed = useContext(EmbedCtx)
  // First render: a guess (the tab has no page yet). Settled before paint by the layout effect.
  const [page, setPage] = useState(() => !!embed && embed.claim.owner == null)
  useLayoutEffect(() => {
    if (!embed) { setPage(false); return }
    const c = embed.claim
    if (c.owner == null) c.owner = id
    setPage(c.owner === id)
    return () => { if (c.owner === id) c.owner = null }
  }, [embed?.claim, id]) // eslint-disable-line react-hooks/exhaustive-deps
  const embedded = !!embed && page
  const stack = useContext(StackCtx)
  if (!embedded && !onBack) onBack = stack?.back ?? (stack?.nested ? onClose : undefined)
  // Escape and the phone's Back go one level back (child screen) or close (root screen).
  useDialog(embedded ? none : ref, onBack ?? onClose)
  const name = embedded && embed.title ? embed.title : title
  // Tab page: a compact top bar (rabbt mark, the header icons) stays put; the big title and its
  // one-line purpose scroll with the page. Once the big title has scrolled away, the bar shows
  // the page name instead of the mark, so you always know where you are.
  const scrollRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const [scrolled, setScrolled] = useState(false)
  const tabPage = embedded && !onBack
  useEffect(() => {
    if (!tabPage) return
    const el = titleRef.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(([e]) => setScrolled(!e!.isIntersecting), { root: scrollRef.current, threshold: 0 })
    io.observe(el)
    return () => io.disconnect()
  }, [tabPage])
  const extras = (embedded && embed.top) || headerExtra
    ? <>{embedded && embed.top}{headerExtra}</> : null
  const body = (
    <>
      {tabPage ? (
        <header className={cn('tab-topbar shrink-0 bg-(--bg) pt-[env(safe-area-inset-top)]', scrolled && 'tab-topbar--scrolled')}>
          <div className="mx-auto flex h-14 max-w-xl items-center gap-2 pl-5 pr-2">
            <div className="relative h-full min-w-0 flex-1">
              <span className={cn('tab-topbar__slot', scrolled && 'is-off')} aria-hidden={scrolled || undefined}><BrandMark /></span>
              <span className={cn('tab-topbar__slot tab-topbar__name', !scrolled && 'is-off')} aria-hidden>{name}</span>
            </div>
            {embed.action}
          </div>
        </header>
      ) : (
        <header className="shrink-0 border-b border-(--border) bg-(--bg) px-3 pb-3 pt-[max(10px,env(safe-area-inset-top))]">
          <div className="flex items-center gap-2">
            {onBack ? (
              <button type="button" className="modal-close" aria-label="Back" onClick={onBack}><ChevronLeft className="size-6" /></button>
            ) : <span className="modal-close invisible" aria-hidden />}
            <div className="min-w-0 flex-1 text-center">
              <h2 className="line-clamp-2 break-words font-display text-title leading-tight text-(--brand)">{name}</h2>
              {subtitle && <p className="mt-0.5 line-clamp-2 text-meta leading-snug text-(--text-muted)">{subtitle}</p>}
            </div>
            {/* X: a root screen, or a step/child screen whose close leaves entirely (a wizard step,
                a thread inside the inbox), so there is always one tap all the way out. */}
            {embedded || !onClose || onClose === onBack ? <span className="modal-close invisible" aria-hidden />
              : <button type="button" className="modal-close" aria-label="Close" onClick={onClose}><X className="size-5" /></button>}
          </div>
          {extras && <div className="mx-auto mt-3 max-w-xl">{extras}</div>}
        </header>
      )}
      <div ref={scrollRef} className="settings min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {tabPage && (
          <div className="mx-auto w-full max-w-xl px-5 pb-1 pt-2">
            <h1 ref={titleRef} className="m-0 font-display text-display text-(--brand)">{name}</h1>
            {subtitle && <p className="m-0 mt-1 text-small leading-snug text-(--text-secondary)">{subtitle}</p>}
            {extras && <div className="mt-4">{extras}</div>}
          </div>
        )}
        <div className={cn('mx-auto flex w-full max-w-xl flex-col gap-7 px-5 pb-12', tabPage ? 'pt-6' : 'pt-5')}>
          {embedded && embed.lead}
          {children}
        </div>
      </div>
      {footer && (
        <footer className={cn('shrink-0 border-t border-(--border) bg-(--bg) px-5 pt-3.5',
          embedded ? 'pb-3.5' : 'pb-[max(14px,env(safe-area-inset-bottom))]')}>
          <div className="mx-auto flex w-full max-w-xl gap-3">{footer}</div>
        </footer>
      )}
    </>
  )
  // Whatever a screen opens inside itself is an overlay again, never the tab page.
  const inner = (
    <EmbedCtx.Provider value={null}>
      <StackCtx.Provider value={embedded ? null : NESTED}>{body}</StackCtx.Provider>
    </EmbedCtx.Provider>
  )
  if (embedded) {
    return <section className="plan-screen plan-screen--tab" aria-label={name}>{inner}</section>
  }
  return (
    <div ref={ref} tabIndex={-1} className={cn('plan-screen', closing && 'plan-screen--exit')} role="dialog" aria-modal aria-label={title}>
      {inner}
    </div>
  )
}

/** The rabbt mark and wordmark: the app's name in the top bar of every tab. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn('flex items-center gap-2.5', className)}>
      <span className="logo-tile flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-(--brand)">
        <RabbitLogo size={26} />
      </span>
      <span className="font-display text-title-md leading-none text-(--brand)">rabbt</span>
    </span>
  )
}

/** Where you are in a wizard: "About you" and "Step 3 of 6" over one even bar that fills as you go.
 *  ``names`` labels each step; the bar is one track (no segments of different widths). */
export function Progress({ step, total, names }: { step: number; total: number; names?: string[] }) {
  const pct = Math.round(((step + 1) / total) * 100)
  return (
    <div className="mx-auto mt-2 flex w-full max-w-xl flex-col gap-1.5 px-1">
      <div className="flex items-baseline justify-between gap-3 text-meta">
        <span className="font-semibold text-(--text)">{names?.[step] ?? ''}</span>
        <span className="tabular-nums text-(--text-muted)">Step {step + 1} of {total}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-(--bg-inset)" role="progressbar"
        aria-valuemin={1} aria-valuemax={total} aria-valuenow={step + 1} aria-valuetext={`Step ${step + 1} of ${total}${names?.[step] ? `: ${names[step]}` : ''}`}>
        <span className="block h-full rounded-full bg-(--accent) transition-[width] duration-300" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/** Big friendly heading at the top of a wizard step. */
export function StepIntro({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="px-1">
      <p className="m-0 text-meta font-semibold text-(--accent)">{eyebrow}</p>
      <h3 className="mt-1.5 font-display text-display-sm leading-tight text-(--brand)">{title}</h3>
      {children && <p className="mt-2 text-body-lg leading-snug text-(--text-secondary)">{children}</p>}
    </div>
  )
}

/** A labeled block inside a card. */
/** A labelled field. The label names the group, and any text control inside that has no
 *  accessible name of its own is labelled by it (and described by the hint). */
export function Field({ label, hint, children, className }: {
  label: React.ReactNode; hint?: React.ReactNode; children: React.ReactNode; className?: string
}) {
  const id = useId()
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.querySelectorAll<HTMLElement>('input:not([type=hidden]):not([type=file]), textarea, select').forEach((el) => {
      if (el.hasAttribute('aria-label') || (el.getAttribute('aria-labelledby') ?? id) !== id) return
      if (el.id && box.current?.querySelector(`label[for="${CSS.escape(el.id)}"]`)) return
      el.setAttribute('aria-labelledby', id)
      if (hint) el.setAttribute('aria-describedby', `${id}-hint`)
    })
  })
  return (
    <div ref={box} role="group" aria-labelledby={id} className={cn('flex flex-col gap-2.5 px-5 py-4', className)}>
      <span id={id} className="flex flex-wrap items-center gap-1 text-meta font-semibold text-(--text-secondary)">{label}</span>
      {children}
      {hint && <span id={`${id}-hint`} className="text-meta leading-snug text-(--text-muted)">{hint}</span>}
    </div>
  )
}

export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface) shadow-[var(--shadow-sm)]', className)}>{children}</div>
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
  return <div className="flex flex-wrap gap-x-2 gap-y-2.5">{children}</div>
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
      className={cn('flex w-full flex-col items-start gap-1 rounded-xl border px-4 py-3.5 text-left transition-colors',
        selected ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface) active:bg-(--bg-inset)')}>
      <span className={cn('text-lead font-medium', selected ? 'text-(--accent)' : 'text-(--text)')}>{title}</span>
      <span className="text-small leading-snug text-(--text-muted)">{description}</span>
    </button>
  )
}

/** A number picked from a dropdown (the phone's native wheel/list): min..max by step, plus "–"
 *  for not set. A saved value that isn't on the grid (e.g. 72.3 kg) is kept as its own option.
 *  `typical` (optional) is listed first under "Common" so nobody scrolls from 30 kg to 75. */
export function NumberStepper({ value, onChange, step = 1, min, max, suffix, decimals = 0, label, typical }: {
  value: number | null | undefined; onChange: (v: number | null) => void
  step?: number; min: number; max: number; suffix?: string; decimals?: number; label: string
  typical?: number[]
}) {
  const v = value ?? null
  const fmt = (n: number) => n.toFixed(decimals)
  const opts: number[] = []
  for (let n = min; n <= max + 1e-9; n += step) opts.push(Math.round(n * 10 ** decimals) / 10 ** decimals)
  if (v != null && !opts.some((o) => Math.abs(o - v) < 1e-9)) {
    opts.push(v); opts.sort((a, b) => a - b)
  }
  void typical  // kept for callers; "Common" picks were dropped (people didn't see themselves in them)
  const unit = suffix ? ` ${suffix}` : ''
  return (
    <div className="relative">
      <select aria-label={label} value={v == null ? '' : fmt(v)}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        className={cn('h-12 w-full appearance-none rounded-md border border-input bg-transparent pl-3 pr-10 text-title-sm tabular-nums',
          'text-(--text) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring', v == null && 'text-(--text-muted)')}>
        <option value="">Choose {label}…</option>
        {opts.map((n) => <option key={n} value={fmt(n)}>{fmt(n)}{unit}</option>)}
      </select>
      <ChevronDown aria-hidden className="pointer-events-none absolute right-3 top-1/2 size-5 -translate-y-1/2 text-(--text-muted)" />
    </div>
  )
}

export const inputCls = 'h-12 w-full rounded-lg border border-input bg-(--bg-surface) px-3.5 text-body-lg text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
export const areaCls = 'min-h-[96px] w-full rounded-lg border border-input bg-(--bg-surface) px-3.5 py-3 text-body-lg text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
