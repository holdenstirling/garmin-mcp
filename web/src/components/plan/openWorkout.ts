// Open the full workout page for one plan session (zones, cadence, distance, steps, how it went).
// screens/Chat.tsx listens for the event and shows the page (lib/workoutnav.ts openWorkout is the
// same contract: { id, date }).
export const OPEN_WORKOUT_EVENT = 'rabbit:open-workout'

export function openWorkoutPage(id: string, date: string) {
  try { window.dispatchEvent(new CustomEvent(OPEN_WORKOUT_EVENT, { detail: { id, date } })) } catch { /* old browsers */ }
}
