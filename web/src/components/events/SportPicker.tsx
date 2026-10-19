// The event form's sport: one dropdown of every sport (lib/sports, grouped: Running, Cycling,
// Team sports, Racket sports...) with the picked sport's icon beside it, plus a name field for
// "Something else". A native select: the phone's own picker, keyboard and screen reader friendly.
import { useId } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SPORT_GROUPS, SPORT_ICON, type SportId } from '@/lib/sports'
import { inputCls } from '@/components/plan/ui'

export function SportPicker({ value, other, onChange, onOther, label = 'Sport' }: {
  value: SportId | null
  /** the free-text name when the sport is Something else */
  other?: string
  onChange: (id: SportId) => void
  onOther: (name: string) => void
  label?: string
}) {
  const id = useId()
  const Icon = value ? SPORT_ICON[value] : null
  return (
    <div className="flex flex-col gap-2">
      <div className="relative flex items-center gap-2.5">
        <span aria-hidden className={cn('flex size-11 shrink-0 items-center justify-center rounded-xl',
          Icon ? 'bg-(--accent-subtle) text-(--accent)' : 'bg-(--bg-inset) text-(--text-muted)')}>
          {Icon ? <Icon className="size-6" /> : <span className="text-body">?</span>}
        </span>
        <div className="relative min-w-0 flex-1">
          <select id={id} aria-label={label} value={value ?? ''}
            onChange={(e) => e.target.value && onChange(e.target.value as SportId)}
            className={cn(inputCls, 'h-11 w-full appearance-none pr-10 text-body-lg', !value && 'text-(--text-muted)')}>
            <option value="" disabled>Pick a sport</option>
            {SPORT_GROUPS.map((g) => (
              <optgroup key={g.group} label={g.group}>
                {g.sports.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </optgroup>
            ))}
          </select>
          <ChevronDown aria-hidden className="pointer-events-none absolute right-3 top-1/2 size-5 -translate-y-1/2 text-(--text-muted)" />
        </div>
      </div>
      {value === 'other' && (
        <input className={inputCls} aria-label="Which sport" value={other ?? ''} maxLength={40}
          placeholder="Which sport? e.g. Cornhole, Disc golf" onChange={(e) => onOther(e.target.value)} />
      )}
    </div>
  )
}
