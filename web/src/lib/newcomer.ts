// Newcomers (server: /me.newcomer, POST /api/newcomer): the one Getting started checklist
// (set your area, do one thing near you, get a plan), first-week mode (a calmer app until the
// first real thing is done, or for 7 days; "Show everything" in Me turns it off) and the
// one-time tips, all stored on the person's own profile.
import { useSyncExternalStore } from 'react'
import { postJSON } from '@/lib/api'

export type TipId = 'near_me' | 'plan' | 'friends' | 'today' | 'levels'
export type Newcomer = {
  since: string; days: number | null
  steps: { area: boolean; job: boolean; plan: boolean }
  first_week: boolean; show_all: boolean; checklist_hidden: boolean; tips: TipId[]
}

let current: Newcomer | null = null
const listeners = new Set<() => void>()
function set(n: Newcomer | null) {
  current = n
  listeners.forEach((l) => l())
}
/** The app shell publishes /me.newcomer here; screens read it with useNewcomer(). */
export function setNewcomer(n: Newcomer | null | undefined) {
  if (JSON.stringify(n ?? null) !== JSON.stringify(current)) set(n ?? null)
}
export function useNewcomer(): Newcomer | null {
  return useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l) } }, () => current, () => current)
}
/** True while the app should stay calm (first week, nothing done yet, not "Show everything"). */
export const useFirstWeek = () => useNewcomer()?.first_week === true

async function send(body: Record<string, unknown>): Promise<void> {
  try { set(await postJSON<Newcomer>('/api/newcomer', body)) } catch { /* best effort */ }
}
/** A checklist step just got done (Chat shows a small cheer). */
export const STEP_DONE_EVENT = 'rabbit:newcomer-step'
function cheer(step: 'area' | 'job' | 'plan') {
  try { window.dispatchEvent(new CustomEvent(STEP_DONE_EVENT, { detail: step })) } catch { /* old browsers */ }
}
let jobSent = false
/** RSVP'd to a run or posted one: checklist step 2. */
export function markJob(): void {
  if (jobSent || current?.steps.job) return
  jobSent = true
  if (current) { set({ ...current, steps: { ...current.steps, job: true } }); cheer('job') }
  void send({ done: 'job' })
}
export function seeTip(id: TipId): void {
  if (current && !current.tips.includes(id)) set({ ...current, tips: [...current.tips, id] })
  void send({ tip: id })
}
export const setShowAll = (on: boolean) => send({ show_all: on })
export const hideChecklist = () => send({ checklist_hidden: true })
/** Mark the area step done right away when an area is saved (the server agrees on next /me). */
export function markArea(): void {
  if (current && !current.steps.area) { set({ ...current, steps: { ...current.steps, area: true } }); cheer('area') }
}
export function markPlan(): void {
  if (current && !current.steps.plan) { set({ ...current, steps: { ...current.steps, plan: true } }); cheer('plan') }
}
