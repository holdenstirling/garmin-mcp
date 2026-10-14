// Rabbit's motion kit: shared helpers. Every effect is decorative (aria-hidden), short
// (<= 1.2 s), transform/opacity only, and off under prefers-reduced-motion.
import { useCallback, useSyncExternalStore } from 'react'
import { hapticTap } from '@/lib/haptics'

export function reducedMotion(): boolean {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return true }
}

// ------------------------------------------------------------ celebrate ---
export type BurstKind = 'xp' | 'challenge' | 'badge' | 'plan' | 'race' | 'checkin' | 'level' | 'kudos' | 'quest'
export type Burst = { id: number; x: number; y: number; kind: BurstKind }
type Target = Element | { x: number; y: number } | null | undefined

let current: Burst | null = null
let seq = 0
let timer = 0
const subs = new Set<() => void>()
const emit = () => subs.forEach((f) => f())

/** One burst at a time: a new one replaces the running one. Hidden with reduced motion (the
 *  light haptic tap still fires where the device supports it: lib/haptics). */
export function celebrate(target: Target, kind: BurstKind = 'xp'): void {
  if (typeof window === 'undefined') return
  hapticTap()
  if (reducedMotion()) return
  let x = window.innerWidth / 2, y = window.innerHeight / 3
  if (target instanceof Element) {
    const r = target.getBoundingClientRect()
    if (r.width || r.height) { x = r.left + r.width / 2; y = r.top + r.height / 2 }
  } else if (target) { x = target.x; y = target.y }
  current = { id: ++seq, x, y, kind }
  window.clearTimeout(timer)
  timer = window.setTimeout(() => { current = null; emit() }, 1200)
  emit()
}

export function useBurst(): Burst | null {
  return useSyncExternalStore(
    (f) => { subs.add(f); return () => { subs.delete(f) } },
    () => current, () => null,
  )
}

/** ``const celebrate = useCelebrate(); celebrate(el | {x, y}, 'badge')`` */
export function useCelebrate(): (target: Target, kind?: BurstKind) => void {
  return useCallback((t: Target, k?: BurstKind) => celebrate(t, k), [])
}

// -------------------------------------------------------- once per day ---
/** True the first time ``key`` is asked on ``day`` (then remembered). Storage off -> false,
 *  so effects never repeat on every open in private mode. */
export function firstToday(key: string, day: string): boolean {
  try {
    const k = `rabbit.fx.${key}`
    if (window.localStorage.getItem(k) === day) return false
    window.localStorage.setItem(k, day)
    return true
  } catch { return false }
}

/** Reads and updates a remembered number; returns the previous one (null the first time). */
export function swapNumber(key: string, value: number): number | null {
  try {
    const k = `rabbit.fx.${key}`
    const prev = window.localStorage.getItem(k)
    window.localStorage.setItem(k, String(value))
    return prev == null || prev === '' || Number.isNaN(Number(prev)) ? null : Number(prev)
  } catch { return null }
}

// ------------------------------------------------- Rabbit reply (tab bar) ---
export const REPLY_DONE_EVENT = 'rabbit:reply-done'
/** Rabbit finished a reply while another tab was showing: the Rabbit tab wiggles. */
export function signalReplyDone(): void {
  try { window.dispatchEvent(new Event(REPLY_DONE_EVENT)) } catch { /* no window */ }
}
