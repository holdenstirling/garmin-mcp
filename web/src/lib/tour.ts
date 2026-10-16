// The one-minute first-run tour (components/onboarding/Tour.tsx): shown once per account on
// this device, and again from Me > Look and feel > Take the tour.
export const TOUR_EVENT = 'rabbit:tour'
const key = (uid: string) => `rabbit.tour.done.${uid}`

export function tourDone(uid: string): boolean {
  try { return localStorage.getItem(key(uid)) === '1' } catch { return true } // no storage: never nag
}
export function markTourDone(uid: string) {
  try { localStorage.setItem(key(uid), '1') } catch { /* ignore */ }
}
export function startTour() {
  try { window.dispatchEvent(new CustomEvent(TOUR_EVENT)) } catch { /* ignore */ }
}
