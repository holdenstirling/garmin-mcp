// Open the Plan tab on one day (Day view of components/plan/PlanCalendar). Contract shared with
// the calendar: it reads these two sessionStorage keys when it mounts, and listens for the event
// while already mounted; screens/Chat.tsx switches to the Plan tab on the event.
export const OPEN_PLAN_DAY_EVENT = 'rabbit:open-plan-day'

export function openPlanDay(date: string) {
  try {
    sessionStorage.setItem('rabbit.plancal.view', 'day')
    sessionStorage.setItem('rabbit.plancal.day', date)
  } catch { /* storage off: the event still carries the date */ }
  try { window.dispatchEvent(new CustomEvent(OPEN_PLAN_DAY_EVENT, { detail: date })) } catch { /* old browsers */ }
}
