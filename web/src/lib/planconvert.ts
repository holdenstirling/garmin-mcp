// Turn a race's plan FILE (a coach's or app's plan Rabbit reads week by week) into a real Rabbit
// plan: the file goes through the same import as an upload (server: planimport_web from_goal),
// the athlete reviews the result, and applying it gives every day full workouts (zones, pace,
// cadence), moving, Garmin sync. screens/Chat.tsx listens for the event and opens the flow.
import { sendJSON } from '@/lib/api'
import type { Preview } from '@/lib/planimport'

export const CONVERT_PLAN_EVENT = 'rabbit:convert-plan'

export function startPlanConversion() {
  try { window.dispatchEvent(new CustomEvent(CONVERT_PLAN_EVENT)) } catch { /* old browsers */ }
}

export const importFromGoal = () => sendJSON<{ preview: Preview }>('POST', '/api/plan/import/from-goal', {})
