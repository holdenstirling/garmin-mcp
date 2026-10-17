// Open the full workout page (components/workout/WorkoutDayScreen) for any plan session, from
// anywhere: Home's week and Up next, the Schedule's Day / Week / list views, search, moments.
// screens/Chat.tsx listens and shows the page. Contract: event 'rabbit:open-workout' with
// detail { id: <session id>, date: 'YYYY-MM-DD' }.
export const OPEN_WORKOUT_EVENT = 'rabbit:open-workout'
export type OpenWorkout = { id: string; date: string }

export function openWorkout(id: string, date: string) {
  try { window.dispatchEvent(new CustomEvent<OpenWorkout>(OPEN_WORKOUT_EVENT, { detail: { id, date } })) } catch { /* old browsers */ }
}
