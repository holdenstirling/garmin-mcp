// Open plan tools from anywhere (Schedule "+ Add", Adjust my plan, Rabbit, search):
// screens/Chat.tsx switches to Schedule > Plan; PlanEditor opens the tool. A pending request is
// kept in sessionStorage so it still opens when PlanEditor mounts after the tab switch.
export const OPEN_TRAVEL_EVENT = 'rabbit:open-travel'
const KEY = 'rabbit.plan.travel'

export function openTravel() {
  try { sessionStorage.setItem(KEY, '1') } catch { /* the event still opens it */ }
  try { window.dispatchEvent(new CustomEvent(OPEN_TRAVEL_EVENT)) } catch { /* old browsers */ }
}

/** true once if a travel request is waiting (and clears it). */
export function takeTravelRequest(): boolean {
  try {
    if (sessionStorage.getItem(KEY) !== '1') return false
    sessionStorage.removeItem(KEY)
    return true
  } catch { return false }
}
