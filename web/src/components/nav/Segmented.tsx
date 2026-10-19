// Two or three views of one tab ("Overview | Weekly recap", "My races | Explore").
import type React from 'react'
import { cn } from '@/lib/utils'

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: readonly (readonly [T, string])[]; onChange: (v: T) => void; label: string
}) {
  // One pill slides to the selected option (styles/rabbit.css .seg__pill; still under reduced motion).
  const idx = Math.max(0, options.findIndex(([v]) => v === value))
  return (
    <div role="tablist" aria-label={label} className="seg mx-auto mt-2 flex max-w-xl rounded-full bg-(--bg-inset) p-0.5"
      style={{ '--seg-i': idx, '--seg-n': options.length } as React.CSSProperties}
      onKeyDown={(e) => {
        // Arrow keys move between the views (one tab stop for the whole control).
        const i = options.findIndex(([v]) => v === value)
        const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
        if (!d || i < 0) return
        e.preventDefault()
        const next = options[(i + d + options.length) % options.length]![0]
        onChange(next)
        ;(e.currentTarget.querySelector(`[data-v="${next}"]`) as HTMLElement | null)?.focus()
      }}>
      <span className="seg__pill" aria-hidden />
      {options.map(([v, l]) => (
        <button key={v} type="button" role="tab" data-v={v} aria-selected={value === v} tabIndex={value === v ? 0 : -1} onClick={() => onChange(v)}
          className={cn('min-h-11 flex-1 rounded-full text-small font-medium transition-colors',
            value === v ? 'text-(--text)' : 'text-(--text-muted)')}>
          {l}
        </button>
      ))}
    </div>
  )
}
