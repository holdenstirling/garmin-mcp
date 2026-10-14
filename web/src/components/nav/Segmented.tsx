// Two or three views of one tab ("Overview | Weekly recap", "My races | Explore").
import { cn } from '@/lib/utils'

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: readonly (readonly [T, string])[]; onChange: (v: T) => void; label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="mx-auto mt-2 flex max-w-xl gap-1 rounded-full bg-(--bg-inset) p-0.5">
      {options.map(([v, l]) => (
        <button key={v} type="button" role="tab" aria-selected={value === v} onClick={() => onChange(v)}
          className={cn('min-h-10 flex-1 rounded-full text-[0.7647rem] font-medium transition-colors',
            value === v ? 'bg-(--bg-surface) text-(--text) shadow-sm' : 'text-(--text-muted)')}>
          {l}
        </button>
      ))}
    </div>
  )
}
