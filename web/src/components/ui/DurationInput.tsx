// Time entry that works on a phone's number pad (which has no ":" key).
// Separate boxes for hours / minutes / seconds; the value is a "h:mm:ss" (or "m:ss") string.
// Pasting or typing "5:30:00" into any box fills all of them.
import { useEffect, useId, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

type Parts = { h: string; m: string; s: string }

const digits = (v: string, n: number) => v.replace(/\D/g, '').slice(0, n)

export function splitTime(v: string | null | undefined, withHours: boolean): Parts {
  const p = (v ?? '').trim().split(':').map((x) => x.replace(/\D/g, ''))
  if (!p[0]) return { h: '', m: '', s: '' }
  if (withHours) {
    if (p.length >= 3) return { h: p[0]!, m: p[1]!, s: p[2]! }
    if (p.length === 2) return { h: '', m: p[0]!, s: p[1]! }  // "45:00" -> 0 h 45 m
    return { h: p[0]!, m: '', s: '' }
  }
  return { h: '', m: p[0]!, s: p[1] ?? '' }
}

/** "" when empty; otherwise "h:mm:ss" (hours > 0) or "m:ss". Minutes over 59 roll into hours. */
export function joinTime({ h, m, s }: Parts, withHours = true): string {
  if (!h && !m && !s) return ''
  let hh = Number(h || 0), mm = Number(m || 0)
  const ss = Math.min(Number(s || 0), 59)
  if (withHours) { hh += Math.floor(mm / 60); mm %= 60 }
  const pad = (n: number) => String(n).padStart(2, '0')
  return hh > 0 ? `${hh}:${pad(mm)}:${pad(ss)}` : `${mm}:${pad(ss)}`
}

const box = 'h-11 w-full min-w-0 rounded-md border border-input bg-transparent px-2 text-center text-base tabular-nums text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50'

export function DurationInput({ value, onChange, onBlur, withHours = true, label, disabled, className, placeholder = '5:30:00' }: {
  value: string | null | undefined
  onChange: (v: string) => void
  onBlur?: (v: string) => void
  withHours?: boolean
  /** Accessible name of the whole group, e.g. "Target time". */
  label: string
  disabled?: boolean
  className?: string
  placeholder?: string
}) {
  const [parts, setParts] = useState<Parts>(() => splitTime(value, withHours))
  const last = useRef(joinTime(parts, withHours))
  const id = useId()
  const ph = splitTime(placeholder, withHours)
  useEffect(() => {  // outside changes (e.g. a reset) win; our own echo doesn't reset the boxes
    if ((value ?? '') !== last.current) { const p = splitTime(value, withHours); setParts(p); last.current = joinTime(p, withHours) }
  }, [value, withHours])

  function set(p: Parts) {
    setParts(p)
    const v = joinTime(p, withHours)
    last.current = v
    onChange(v)
  }
  function onField(k: keyof Parts, raw: string, max: number) {
    if (raw.includes(':')) { set(splitTime(raw, withHours)); return }  // pasted or typed a full time
    set({ ...parts, [k]: digits(raw, max) })
  }
  const fields: [keyof Parts, string, number][] = [
    ...(withHours ? [['h', 'hours', 2] as [keyof Parts, string, number]] : []),
    ['m', 'minutes', withHours ? 2 : 3], ['s', 'seconds', 2],
  ]
  return (
    <div role="group" aria-label={label} className={cn('flex items-center gap-1.5', className)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) onBlur?.(joinTime(parts, withHours)) }}>
      {fields.map(([k, name, max], i) => (
        <div key={k} className="flex min-w-0 flex-1 items-center gap-1.5">
          {i > 0 && <span aria-hidden className="text-(--text-muted)">:</span>}
          <label className="flex min-w-0 flex-1 flex-col items-center gap-0.5" htmlFor={`${id}-${k}`}>
            <input id={`${id}-${k}`} className={box} inputMode="numeric" autoComplete="off" enterKeyHint="next"
              aria-label={`${label}, ${name}`} placeholder={ph[k] || '0'} value={parts[k]} disabled={disabled}
              onChange={(e) => onField(k, e.target.value, max)} />
            <span aria-hidden className="text-[0.6471rem] text-(--text-muted)">{name}</span>
          </label>
        </div>
      ))}
    </div>
  )
}
