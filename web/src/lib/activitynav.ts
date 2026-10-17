// Open the full page for one recorded workout (Garmin activity id, or "<source>:<id>" for a
// workout another app recorded). screens/Chat.tsx listens and shows components/workout/
// ActivityScreen. Planned sessions open their own page (lib/workoutnav openWorkout).
export const OPEN_ACTIVITY_EVENT = 'rabbit:open-activity'
export type OpenActivity = { id: string }

export function openActivity(id: string | number) {
  try { window.dispatchEvent(new CustomEvent<OpenActivity>(OPEN_ACTIVITY_EVENT, { detail: { id: String(id) } })) } catch { /* old browsers */ }
}
