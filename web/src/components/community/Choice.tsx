// A row of pill radio buttons (sport, level, who can join, audience).
import { cn } from '@/lib/utils'

export function Choice<T extends string>({ value, options, onChange, label }: {
  value: T; options: readonly (readonly [T, string])[]; onChange: (v: T) => void; label: string
}) {
  return (
    <div className="-mx-0.5 flex flex-wrap gap-1" role="radiogroup" aria-label={label}>
      {options.map(([v, l]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className="hit-44 inline-flex min-h-9 items-center px-0.5">
          <span className={cn('rounded-full border px-2.5 py-1 text-[0.7059rem] font-medium',
            value === v ? 'border-(--accent) bg-(--accent-subtle) text-(--accent)' : 'border-(--border) text-(--text-secondary)')}>{l}</span>
        </button>
      ))}
    </div>
  )
}
