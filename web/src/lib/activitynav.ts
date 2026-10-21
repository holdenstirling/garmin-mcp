// Open the full page for one recorded workout (Garmin activity id, or "<source>:<id>" for a
// workout another app recorded). screens/Chat.tsx listens and shows components/workout/
// ActivityScreen. Planned sessions open their own page (lib/workoutnav openWorkout).
export const OPEN_ACTIVITY_EVENT = 'rabbit:open-activity'
/** ``of``: a friend's user id, for their workout (what they share, never heart rate) */
export type OpenActivity = { id: string; of?: string }

export function openActivity(id: string | number, of?: string | null) {
  const detail: OpenActivity = of ? { id: String(id), of } : { id: String(id) }
  try { window.dispatchEvent(new CustomEvent<OpenActivity>(OPEN_ACTIVITY_EVENT, { detail })) } catch { /* old browsers */ }
}
