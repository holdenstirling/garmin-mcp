// Race checklist (server: racechecklist.py): a timeline of things to do for a race, challenge or
// trip, from 12+ weeks out to after the race. Ticks, hidden items and your own items are saved
// on your account. openChecklist(eventId) shows the page (screens/Chat.tsx listens).
import { getJSON, sendJSON } from '@/lib/api'

export type BucketId = 'early' | 'build' | 'two_weeks' | 'race_week' | 'eve' | 'morning' | 'after'
export type ChecklistItem = {
  id: string; text: string; bucket: BucketId; note?: string; custom?: boolean; checked: boolean; due: string
}
export type ChecklistBucket = {
  id: BucketId; label: string; start: string | null; due: string; current: boolean; past: boolean
  done: number; total: number; items: ChecklistItem[]
}
export type Checklist = {
  event: { id: string; name: string; date: string; kind?: string; type?: string; distance?: string; priority?: string; location?: string }
  days_out: number; current: BucketId; category: string; done: number; total: number
  buckets: ChecklistBucket[]; hidden: ChecklistItem[]
}
export type ChecklistNext = {
  event: Checklist['event']; days_out: number; done: number; total: number
  window: { id: BucketId; label: string; done: number; total: number; due: string }
  next: (ChecklistItem & { bucket_label: string })[]
}
export type ChecklistAction =
  | { action: 'check' | 'uncheck' | 'hide' | 'unhide' | 'delete'; item: string }
  | { action: 'add'; text: string; bucket: BucketId }

export const getChecklist = (eventId: string) => getJSON<Checklist>(`/api/events/${encodeURIComponent(eventId)}/checklist`)
export const actChecklist = (eventId: string, a: ChecklistAction) =>
  sendJSON<Checklist>('POST', `/api/events/${encodeURIComponent(eventId)}/checklist`, a)
export const checklistSummary = () => getJSON<{ events: Record<string, { done: number; total: number }> }>('/api/checklist/summary')
export const checklistNext = () => getJSON<{ next: ChecklistNext | null }>('/api/checklist/next')

/** Fired after any change, so cards elsewhere (Home, race cards) refresh their counts. */
export const CHECKLIST_CHANGED_EVENT = 'rabbit:checklist-changed'
export const OPEN_CHECKLIST_EVENT = 'rabbit:open-checklist'
export function openChecklist(eventId: string) {
  try { window.dispatchEvent(new CustomEvent<string>(OPEN_CHECKLIST_EVENT, { detail: eventId })) } catch { /* old browsers */ }
}
export function announceChecklist() {
  try { window.dispatchEvent(new CustomEvent(CHECKLIST_CHANGED_EVENT)) } catch { /* ignore */ }
}

/** "by Oct 30" (or "today" / "tomorrow"). */
export function dueLabel(iso: string, today = new Date()): string {
  const d = new Date(`${iso}T12:00:00`)
  const t = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 12)
  const days = Math.round((d.getTime() - t.getTime()) / 86_400_000)
  if (days === 0) return 'today'
  if (days === 1) return 'by tomorrow'
  return `by ${d.toLocaleDateString([], { month: 'short', day: 'numeric' })}`
}
