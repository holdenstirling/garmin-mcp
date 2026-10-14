// Gamification: level and XP, setup quests, this week's goal, streak and celebrations.
import { getJSON, sendJSON } from '@/lib/api'

export type QuestId = 'garmin' | 'sports' | 'goal' | 'plan' | 'sync' | 'notify' | 'calendar' | 'oura' | 'coach' | 'gear'
export type Quest = { id: QuestId; title: string; hint: string; xp: number; optional: boolean; done: boolean }
export type Progress = {
  level: number; name: string; xp: number; level_xp: number; level_span: number; to_next: number
  next_name: string | null; gained: number; level_up: boolean
  new_badges: { id: string; title: string; description: string }[]
  quests: Quest[]; setup: { done: number; total: number }
  week: { kind: 'plan' | 'active'; done: number; target: number; label: string }
  streak: { current: number; best: number; today_done: boolean; grace_left: boolean; at_risk: boolean }
  stats_ok: boolean
}

export const getProgress = () => getJSON<Progress>('/api/progress')
export const markProgressSeen = () => sendJSON<{ ok: boolean }>('POST', '/api/progress/seen', {})

/** The next core quest to do, or null when setup is complete. */
export const nextQuest = (p: Progress): Quest | null => p.quests.find((q) => !q.optional && !q.done) ?? null
