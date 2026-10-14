// "Plan adjusts to real life": suggested changes after missed sessions or low recovery.
import { getJSON, sendJSON } from '@/lib/api'
import type { BuiltPlan } from '@/lib/plan'

export type Change = {
  session_id: string; date: string; action: 'ease' | 'shorten' | 'rest' | 'move'
  from: { title: string; sport: string; kind: string; minutes: number | null }
  to: { title?: string; sport: string; kind: string | null; minutes: number | null }
  why: string
}
export type Proposal =
  | { status: 'none' | 'ok' | 'watch' | 'dismissed'; reasons?: string[]; id?: string }
  | { status: 'suggest'; id: string; reasons: string[]; changes: Change[] }

export const getAdjust = () => getJSON<Proposal>('/api/plan/adjust')
export const decideAdjust = (id: string, action: 'apply' | 'dismiss') =>
  sendJSON<{ plan: BuiltPlan; applied: number }>('POST', '/api/plan/adjust', { id, action })
