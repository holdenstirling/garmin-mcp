// One forgiving time field for target times and paces.
// Type it however you like: 5:30:00, 5h30, 5 hours 30 min, 5.5, or just digits on the phone's
// number pad (53000 -> 5:30:00, colons are added as you type). Below the field Rabbit says
// what it read in words ("5 h 30 min"), so a mix-up is obvious before saving.
// -/+ buttons nudge the time; "abc" switches to the full keyboard for letters.
import { useEffect, useId, useRef, useState } from 'react'
import { Minus, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { describeDuration, formatDuration, maskDigits, parseDuration, type Expect } from '@/lib/duration'

const STEP = { hours: 300, minutes: 5 } as const  // 5 min for goal times, 5 s for paces

export function DurationInput({ value, onChange, onBlur, withHours = true, expect, label, disabled, className, placeholder }: {
  value: string | null | undefined
  /** Normalized "h:mm:ss" / "m:ss", or "" while the text can't be read. */
  onChange: (v: string) => void
  onBlur?: (v: string) => void
  /** false: a pace (minutes:seconds). */
  withHours?: boolean
  /** What a bare or ambiguous number means; defaults to hours for goal times, minutes for paces. */
  expect?: Expect
  /** Visible to screen readers; the visible label comes from the surrounding Field. */
  label: string
  disabled?: boolean
  className?: string
  placeholder?: string
}) {
  const mode: Expect = expect ?? (withHours ? 'hours' : 'minutes')
  const [text, setText] = useState(value ?? '')
  const [touched, setTouched] = useState(false)
  const [letters, setLetters] = useState(false)
  const last = useRef(value ?? '')
  const hintId = useId()
  useEffect(() => {  // outside changes (a reset, a saved value) win; our own echo doesn't
    if ((value ?? '') !== last.current) { setText(value ?? ''); last.current = value ?? '' }
  }, [value])

  const sec = parseDuration(text, mode)
  const emit = (t: string) => {
    const s = parseDuration(t, mode)
    const v = s == null ? '' : formatDuration(s)
    last.current = v
    onChange(v)
    return v
  }
  function change(raw: string) {
    const t = /^[\d:]*$/.test(raw) && !raw.includes('::') ? maskDigits(raw.replace(/:/g, '')) : raw
    // Deleting a colon the mask added would otherwise do nothing: drop the digit before it.
    const next = raw.length < text.length && t === text ? maskDigits(text.replace(/\D/g, '').slice(0, -1)) : t
    setText(next)
    emit(next)
  }
  function nudge(dir: 1 | -1) {
    const base = sec ?? 0
    const s = Math.max(0, base + dir * STEP[mode])
    const t = formatDuration(s)
    setText(t); setTouched(true)
    onBlur?.(emit(t))
  }
  function blur() {
    setTouched(true)
    const v = emit(text)
    if (v) setText(v)
    if (v || !text.trim()) onBlur?.(v)  // unreadable text stays on screen, unsaved, with the hint
  }

  const bad = touched && text.trim() !== '' && sec == null
  const example = placeholder ?? (mode === 'hours' ? '5:30:00' : '8:30')
  const btn = 'flex size-11 shrink-0 items-center justify-center rounded-md border border-input text-(--text-secondary) disabled:opacity-40'
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-center gap-2">
        <button type="button" className={btn} aria-label={`${label}: ${mode === 'hours' ? '5 minutes less' : '5 seconds faster'}`}
          disabled={disabled || !sec} onClick={() => nudge(-1)}><Minus className="size-4" aria-hidden /></button>
        <div className="relative min-w-0 flex-1">
          <input className={cn('h-11 w-full rounded-md border bg-transparent px-3 pr-14 text-lg tabular-nums tracking-wide text-(--text)',
            'placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50',
            bad ? 'border-(--danger)' : 'border-input')}
            inputMode={letters ? 'text' : 'numeric'} autoComplete="off" autoCorrect="off" spellCheck={false} enterKeyHint="done"
            aria-label={label} aria-describedby={hintId} aria-invalid={bad || undefined}
            placeholder={example} value={text} disabled={disabled}
            onChange={(e) => change(e.target.value)} onBlur={blur} />
          <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setLetters((v) => !v)}
            className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-[0.7059rem] font-medium text-(--text-muted)"
            aria-label={letters ? 'Use the number pad' : 'Use the full keyboard to type letters like 5h30'}>
            {letters ? '123' : 'abc'}
          </button>
        </div>
        <button type="button" className={btn} aria-label={`${label}: ${mode === 'hours' ? '5 minutes more' : '5 seconds slower'}`}
          disabled={disabled} onClick={() => nudge(1)}><Plus className="size-4" aria-hidden /></button>
      </div>
      <p id={hintId} aria-live="polite" className={cn('text-[0.7059rem]', bad ? 'text-(--danger)' : sec != null ? 'text-(--accent)' : 'text-(--text-muted)')}>
        {bad ? `Couldn't read that. Try ${example}, ${mode === 'hours' ? '5h30 or 530' : '8m30 or 830'}.`
          : sec != null ? `= ${describeDuration(sec)}`
          : mode === 'hours' ? 'Any format works: 5:30:00, 5h30, 5.5 or just 530' : 'Any format works: 8:30, 8m30 or just 830'}
      </p>
    </div>
  )
}
