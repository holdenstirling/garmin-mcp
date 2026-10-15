// One place for haptics: haptic() gives a light 10 ms tap via the Vibration API where it
// exists (Android Chrome and friends) after a success (saved, sent, refreshed, RSVP'd...).
// iOS Safari has no Vibration API, and the hidden-<input switch> workaround no longer fires the
// Taptic Engine on current iOS, so on iPhone this is a no-op.
//
// Off when the person turned "Vibrate on success" off (Settings, per device) or asks for
// reduced motion. Never throws.
const KEY = 'rabbit.haptics'

export function hapticsEnabled(): boolean {
  try { return window.localStorage.getItem(KEY) !== 'off' } catch { return true }
}

export function setHapticsEnabled(on: boolean): void {
  try { if (on) window.localStorage.removeItem(KEY); else window.localStorage.setItem(KEY, 'off') } catch { /* this visit only */ }
}

export function hapticsSupported(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function'
}

export function haptic(ms = 10): void {
  try {
    if (!hapticsSupported() || !hapticsEnabled()) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    navigator.vibrate(ms)
  } catch {
    /* no haptics on this device */
  }
}

/** Older name; same rules as haptic(). */
export const hapticTap = (): void => haptic()
