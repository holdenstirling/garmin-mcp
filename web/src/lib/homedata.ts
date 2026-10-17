// Home cards read the same fitness/fatigue series (ReadinessSnapshot for form, FitnessCountdown
// for the 4-week fitness trend): one request per Home refresh, shared by both cards.
import { getLoad, type Load } from '@/lib/load'

let cached: { key: number; p: Promise<Load> } | null = null

/** The load series for this Home refresh (``key`` = Home's refresh tick). */
export function homeLoad(key: number): Promise<Load> {
  if (!cached || cached.key !== key) {
    const p = getLoad()
    p.catch(() => { if (cached?.p === p) cached = null })  // a failure isn't cached
    cached = { key, p }
  }
  return cached.p
}

export type Call = 'push' | 'normal' | 'ease'

/** One plain call for today from recovery + form. Deterministic, no AI; the strongest signal
 *  wins and becomes the "why". Missing numbers are skipped, never guessed. */
export function readinessCall(x: {
  readiness?: number | null; sleepH?: number | null; hrv?: number | null; hrvBase?: number | null; tsb?: number | null
}): { call: Call; why: string } {
  const { readiness, sleepH, hrv, hrvBase, tsb } = x
  const hrvDrop = hrv != null && hrvBase ? (hrv - hrvBase) / hrvBase : null
  if (readiness != null && readiness < 40) return { call: 'ease', why: `Readiness is low (${readiness}).` }
  if (hrvDrop != null && hrvDrop <= -0.12) return { call: 'ease', why: `HRV is ${Math.round(-hrvDrop * 100)}% under your usual.` }
  if (sleepH != null && sleepH < 6) return { call: 'ease', why: `Only ${fmtH(sleepH)} of sleep.` }
  if (tsb != null && tsb < -25) return { call: 'ease', why: 'Fatigue is high from recent training.' }
  const good = (readiness == null || readiness >= 70) && (sleepH == null || sleepH >= 7)
    && (hrvDrop == null || hrvDrop > -0.05) && (tsb == null || tsb > -10)
  const known = [readiness, sleepH, hrvDrop, tsb].filter((v) => v != null).length
  if (good && known >= 2) return { call: 'push', why: 'Well rested and fresh: a good day for the key session.' }
  return { call: 'normal', why: tsb != null && tsb < -10 ? 'Some fatigue: stick to the plan, keep easy days easy.' : 'Nothing stands out: train as planned.' }
}

export const fmtH = (h: number) => {
  const m = Math.round(h * 60)
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}
