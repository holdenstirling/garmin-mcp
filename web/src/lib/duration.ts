// Forgiving time parsing for target times and paces. Accepts what people actually type:
//   5:30:00  5:30  5.30  5h30  5h 30m  5 hours 30 min  5.5h  330  53000  45m  45 min  1:45:30
//   8:30  8.5  8m30s  830  (paces, read as minutes:seconds)
// `expect` says what a bare / ambiguous number means: "hours" for long goals (330 -> 3 h 30),
// "minutes" for paces and short races (330 -> 3 min 30 s).

export type Expect = 'hours' | 'minutes'

const UNIT = /(\d+(?:[.,]\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|'|seconds?|secs?|s|")/gi

/** Seconds, or null when it can't be read. */
export function parseDuration(raw: string, expect: Expect = 'hours'): number | null {
  const v = raw.trim().toLowerCase().replace(/,/g, '.')
  if (!v) return null

  // 1:45:30 / 5:30 / 8:30 (also "5.30.00" and "5 30 00")
  const sep = v.match(/^(\d{1,3})\s*[:.;\s]\s*(\d{1,2})(?:\s*[:.;\s]\s*(\d{1,2}))?$/)
  if (sep && (v.includes(':') || v.includes(';') || /\s/.test(v) || sep[3] !== undefined || sep[2]!.length === 2)) {
    const [a, b, c] = [Number(sep[1]), Number(sep[2]), sep[3] === undefined ? null : Number(sep[3])]
    if (b > 59 || (c !== null && c > 59)) return null
    if (c !== null) return a * 3600 + b * 60 + c
    return expect === 'hours' && a <= 23 ? a * 3600 + b * 60 : a * 60 + b  // "45:00" is 45 minutes
  }

  // 5h30, 5h 30m 10s, 45 min, 8m30s, 5.5h, 4'30"
  if (/[a-z'"]/.test(v)) {
    let total = 0, seen = false, rest = v
    for (const m of v.matchAll(UNIT)) {
      const n = Number(m[1]), u = m[2]![0]
      total += u === 'h' ? n * 3600 : u === 'm' || u === "'" ? n * 60 : n
      seen = true
      rest = rest.replace(m[0], ' ')
    }
    // a trailing bare number after hours or minutes: "5h30" -> 30 min, "8m30" -> 30 s
    const tail = rest.trim().match(/^(\d{1,2})$/)
    if (tail && seen) {
      const last = [...v.matchAll(UNIT)].pop()![2]![0]
      total += last === 'h' ? Number(tail[1]) * 60 : Number(tail[1])
      rest = ''
    }
    return seen && !rest.trim() ? Math.round(total) : null
  }

  // 5.5 -> 5 h 30 (or 5 min 30 s for paces)
  if (/^\d+\.\d+$/.test(v)) {
    const n = Number(v)
    return Math.round(expect === 'hours' ? n * 3600 : n * 60)
  }

  // digits only, as typed on a phone number pad: read from the right
  if (/^\d{1,6}$/.test(v)) {
    const d = v
    if (d.length <= 2) return expect === 'hours' ? Number(d) * 3600 : Number(d) * 60
    if (d.length <= 4) {  // 330 / 0330 / 1245
      const a = Number(d.slice(0, -2)), b = Number(d.slice(-2))
      if (b > 59) return null
      return expect === 'hours' && a <= 23 ? a * 3600 + b * 60 : a * 60 + b
    }
    const h = Number(d.slice(0, -4)), m = Number(d.slice(-4, -2)), s = Number(d.slice(-2))
    if (m > 59 || s > 59) return null
    return h * 3600 + m * 60 + s
  }
  return null
}

const pad = (n: number) => String(n).padStart(2, '0')

/** "5:30:00" (hours) or "8:30" (under an hour). */
export function formatDuration(sec: number): string {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

/** "5 h 30 min", "45 min", "8 min 30 s" — what we read, in words. */
export function describeDuration(sec: number): string {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60
  const out: string[] = []
  if (h) out.push(`${h} h`)
  if (m || (h && s)) out.push(`${m} min`)
  if (s) out.push(`${s} s`)
  return out.join(' ') || '0 min'
}

/** As-you-type mask for digit-only entry on a number pad: 53000 -> 5:30:00, 330 -> 3:30. */
export function maskDigits(raw: string): string {
  const d = raw.replace(/\D/g, '').slice(0, 6)
  if (d.length <= 2) return d
  if (d.length <= 4) return `${d.slice(0, -2)}:${d.slice(-2)}`
  return `${d.slice(0, -4)}:${d.slice(-4, -2)}:${d.slice(-2)}`
}

/** Short races are timed in minutes ("22:30" for a 5K); everything else in hours. */
export function expectForDistance(distance: string | null | undefined): Expect {
  const d = (distance ?? '').toLowerCase()
  if (/\d{2,}\s?(mile|mi)\b/.test(d)) return 'hours'  // 50 mile, 100 mile
  return /\b(1|3|5|8|10)\s?(k|km)\b|\bmile\b|\b(400|800|1500|1600|3000|5000)\s?m?\b|parkrun/.test(d)
    ? 'minutes' : 'hours'
}
