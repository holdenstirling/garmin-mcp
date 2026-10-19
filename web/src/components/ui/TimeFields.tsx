// Times and paces as separate number boxes: hours / minutes / seconds (or minutes / seconds for
// a pace). Each box opens the number pad, takes at most two digits, never reformats while you
// type, and moves to the next box after two digits. Below, rabbt says what it read in words.
// Optional presets fill all boxes at once (common goal times for a distance).
import { useEffect, useId, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { describeDuration } from '@/lib/duration'

type Parts = { h: string; m: string; s: string }

const pad = (n: number) => String(n).padStart(2, '0')

/** "5:30:00" / "45:00" / "8:30" -> boxes. Unreadable -> empty boxes. */
export function splitTime(v: string | null | undefined, withHours: boolean): Parts {
  const p = (v ?? '').trim().split(':').map((x) => x.trim())
  if (!v || p.some((x) => !/^\d{1,3}$/.test(x))) return { h: '', m: '', s: '' }
  if (p.length === 3) return { h: String(Number(p[0])), m: pad(Number(p[1])), s: pad(Number(p[2])) }
  if (p.length === 2) {
    const a = Number(p[0]), b = Number(p[1])
    // "5:30" as a goal time with hours is 5 h 30 min only when it can't be minutes:seconds;
    // stored goal times are always "h:mm:ss" or "mm:ss", so read two parts as minutes:seconds.
    return withHours && a >= 60 ? { h: String(Math.floor(a / 60)), m: pad(a % 60), s: pad(b) } : { h: '', m: String(a), s: pad(b) }
  }
  return { h: '', m: '', s: '' }
}

/** Boxes -> seconds, or null when a box is out of range or everything is empty. */
export function partsToSeconds({ h, m, s }: Parts): number | null {
  if (!h && !m && !s) return null
  const hh = Number(h || 0), mm = Number(m || 0), ss = Number(s || 0)
  if (![hh, mm, ss].every(Number.isFinite) || mm > 59 || ss > 59) return null
  const total = hh * 3600 + mm * 60 + ss
  return total > 0 ? total : null
}

/** Seconds -> the stored form: "h:mm:ss" from an hour up, else "m:ss". */
export function secondsToTime(sec: number, withHours: boolean): string {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60
  return withHours && h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${h * 60 + m}:${pad(s)}`
}

export function TimeFields({ value, onChange, withHours = true, label, presets, scrollOnMount, className, disabled }: {
  value: string | null | undefined
  /** "h:mm:ss" / "m:ss", or "" while the boxes don't make a time */
  onChange: (v: string) => void
  /** false: a pace (minutes and seconds only) */
  withHours?: boolean
  /** names the group for screen readers ("Target time", "Swim pace") */
  label: string
  /** quick picks, in the stored form ("1:45:00") */
  presets?: string[]
  /** bring the boxes into view when they first appear (they often open below the fold) */
  scrollOnMount?: boolean
  className?: string
  disabled?: boolean
}) {
  const [parts, setParts] = useState<Parts>(() => splitTime(value, withHours))
  const last = useRef(value ?? '')
  const wrap = useRef<HTMLDivElement>(null)
  const refs = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)]
  const hintId = useId()
  useEffect(() => {  // a value set from outside (a preset elsewhere, a reset) replaces the boxes
    if ((value ?? '') !== last.current) { setParts(splitTime(value, withHours)); last.current = value ?? '' }
  }, [value, withHours])
  useEffect(() => {
    if (!scrollOnMount) return
    const t = window.setTimeout(() => wrap.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 60)
    return () => window.clearTimeout(t)
  }, [scrollOnMount])

  const keys: (keyof Parts)[] = withHours ? ['h', 'm', 's'] : ['m', 's']
  const names: Record<keyof Parts, string> = { h: 'hours', m: 'minutes', s: 'seconds' }
  const units: Record<keyof Parts, string> = { h: 'hr', m: 'min', s: 'sec' }
  const sec = partsToSeconds(parts)
  const outOfRange = Number(parts.m || 0) > 59 || Number(parts.s || 0) > 59

  function emit(p: Parts) {
    const s = partsToSeconds(p)
    const v = s == null ? '' : secondsToTime(s, withHours)
    last.current = v
    onChange(v)
  }
  function set(k: keyof Parts, raw: string, i: number) {
    const digits = raw.replace(/\D/g, '').slice(0, k === 'h' ? 2 : 2)
    const next = { ...parts, [k]: digits }
    setParts(next)
    emit(next)
    if (digits.length === 2 && i < keys.length - 1) refs[i + 1]!.current?.focus()
  }
  function key(e: React.KeyboardEvent<HTMLInputElement>, i: number) {
    if (e.key === 'Backspace' && !e.currentTarget.value && i > 0) refs[i - 1]!.current?.focus()
  }
  function pick(v: string) {
    const p = splitTime(v, withHours)
    setParts(p)
    emit(p)
  }

  return (
    <div ref={wrap} className={cn('flex flex-col gap-2', className)} role="group" aria-label={label} aria-describedby={hintId}>
      <div className="flex items-start gap-2">
        {keys.map((k, i) => (
          <label key={k} className="flex flex-col items-center gap-1">
            <input ref={refs[i]} value={parts[k]} disabled={disabled}
              inputMode="numeric" pattern="[0-9]*" autoComplete="off" enterKeyHint={i === keys.length - 1 ? 'done' : 'next'}
              maxLength={2} aria-label={`${label}: ${names[k]}`} placeholder={k === 'h' ? '0' : '00'}
              onChange={(e) => set(k, e.target.value, i)} onKeyDown={(e) => key(e, i)}
              onFocus={(e) => e.currentTarget.select()}
              className={cn('h-14 w-[4.5rem] rounded-lg border bg-(--bg-surface) text-center text-title-sm tabular-nums text-(--text)',
                'placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50',
                (k === 'm' || k === 's') && Number(parts[k] || 0) > 59 ? 'border-(--danger)' : 'border-input')} />
            <span className="text-meta text-(--text-muted)" aria-hidden>{units[k]}</span>
          </label>
        ))}
      </div>
      <p id={hintId} aria-live="polite" className={cn('text-meta', outOfRange ? 'text-(--danger)' : sec != null ? 'text-(--accent)' : 'text-(--text-muted)')}>
        {outOfRange ? 'Minutes and seconds go up to 59.' : sec != null ? `= ${describeDuration(sec)}` : withHours ? 'Hours, minutes and seconds.' : 'Minutes and seconds.'}
      </p>
      {presets && presets.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Quick picks">
          {presets.map((p) => (
            <button key={p} type="button" disabled={disabled} onClick={() => pick(p)}
              className={cn('min-h-11 rounded-full border px-4 text-body tabular-nums',
                value === p ? 'border-(--accent) bg-(--accent-subtle) font-semibold text-(--accent)' : 'border-(--border) text-(--text-secondary)')}>
              {describeDuration(partsToSeconds(splitTime(p, withHours)) ?? 0)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** Common goal times by race distance (stored form), for quick picks. */
export const TARGET_PRESETS: Record<string, string[]> = {
  '5k': ['20:00', '25:00', '30:00', '35:00'],
  '10k': ['45:00', '50:00', '55:00', '1:00:00'],
  'half marathon': ['1:45:00', '2:00:00', '2:15:00', '2:30:00'],
  marathon: ['3:30:00', '4:00:00', '4:30:00', '5:00:00'],
  'sprint triathlon': ['1:15:00', '1:30:00', '1:45:00'],
  'olympic triathlon': ['2:30:00', '2:45:00', '3:00:00', '3:30:00'],
  '70.3': ['5:00:00', '5:30:00', '6:00:00', '6:30:00'],
  '140.6': ['11:00:00', '12:00:00', '13:00:00', '14:00:00'],
  'century ride': ['5:30:00', '6:00:00', '7:00:00'],
}
